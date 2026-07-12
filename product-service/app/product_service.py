"""Product business logic: slug generation, Redis caching, stock guard,
soft delete — with cache invalidation on every write."""

import re
import uuid

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Product
from app.queries import CategoryQuery, ProductQuery
from app.schemas import ProductCreate, ProductOut, ProductUpdate

PRODUCT_CACHE_KEY = "product:{product_id}"
PRODUCT_SLUG_MAX_LENGTH = 200
MAX_SLUG_SUFFIX_ATTEMPTS = 500


# ---------- slugs ----------

def slugify(name: str) -> str:
    """Lowercase, hyphens: 'Super Laptop 3' -> 'super-laptop-3'."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "item"


async def unique_slug(name: str, exists, max_length: int) -> str:
    """Append -2, -3, ... until the slug is free. `exists` is an async
    callback that checks whether a slug is taken."""
    base = slugify(name)[:max_length].rstrip("-")
    candidate = base
    for suffix in range(2, MAX_SLUG_SUFFIX_ATTEMPTS):
        if not await exists(candidate):
            return candidate
        tail = f"-{suffix}"
        candidate = base[: max_length - len(tail)] + tail
    raise RuntimeError(f"Could not find a unique slug for {name!r}")


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
    )


class ProductService:
    def __init__(self, db: AsyncSession, redis: Redis):
        self.redis = redis
        self.products = ProductQuery(db)
        self.categories = CategoryQuery(db)

    # ---------- cache (spec 3.5: product:{uuid}, TTL 300s, DEL on write) ----------

    async def _cache_get(self, product_id: uuid.UUID) -> str | None:
        return await self.redis.get(PRODUCT_CACHE_KEY.format(product_id=product_id))

    async def _cache_set(self, product_id: uuid.UUID, payload_json: str) -> None:
        await self.redis.set(
            PRODUCT_CACHE_KEY.format(product_id=product_id),
            payload_json,
            ex=settings.PRODUCT_CACHE_TTL_SECONDS,
        )

    async def _cache_invalidate(self, product_id: uuid.UUID) -> None:
        await self.redis.delete(PRODUCT_CACHE_KEY.format(product_id=product_id))

    # ---------- reads ----------

    async def get_cached(self, id_or_slug: str) -> tuple[str, str]:
        """Returns (payload_json, cache_state) where cache_state is HIT or MISS."""
        product_id: uuid.UUID | None = None
        try:
            product_id = uuid.UUID(id_or_slug)
        except ValueError:
            pass  # treat as slug

        if product_id is not None:
            cached = await self._cache_get(product_id)
            if cached is not None:
                return cached, "HIT"
            product = await self.products.get_by_id(product_id)
        else:
            product = await self.products.get_by_slug(id_or_slug)
            if product is not None:
                cached = await self._cache_get(product.id)
                if cached is not None:
                    return cached, "HIT"

        if product is None or not product.is_active:
            raise _not_found()

        payload = ProductOut.model_validate(product).model_dump_json()
        await self._cache_set(product.id, payload)
        return payload, "MISS"

    # ---------- writes (every one invalidates the cache) ----------

    async def _require_category(self, category_id: uuid.UUID) -> None:
        if await self.categories.get_by_id(category_id) is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category does not exist",
            )

    async def create(self, body: ProductCreate, created_by: str) -> Product:
        await self._require_category(body.category_id)
        slug = await unique_slug(
            body.name, self.products.slug_exists, PRODUCT_SLUG_MAX_LENGTH
        )
        return await self.products.create(
            name=body.name,
            slug=slug,
            description=body.description,
            price=body.price,
            stock_quantity=body.stock_quantity,
            category_id=body.category_id,
            created_by=uuid.UUID(created_by),
        )

    async def update(self, product_id: uuid.UUID, body: ProductUpdate) -> Product:
        product = await self.products.get_by_id(product_id)
        if product is None:
            raise _not_found()
        await self._require_category(body.category_id)
        product = await self.products.update_fields(
            product,
            name=body.name,
            description=body.description,
            price=body.price,
            category_id=body.category_id,
            is_active=body.is_active,
        )
        await self._cache_invalidate(product.id)
        return product

    async def apply_stock_delta(self, product_id: uuid.UUID, delta: int) -> Product:
        updated = await self.products.apply_stock_delta(product_id, delta)
        if updated is None:
            product = await self.products.get_by_id(product_id)
            if product is None:
                raise _not_found()
            # Spec: 400 with a clear message if delta would go negative
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Stock cannot go below 0: current stock is "
                    f"{product.stock_quantity}, requested delta is {delta}"
                ),
            )
        await self._cache_invalidate(product_id)
        return updated

    async def soft_delete(self, product_id: uuid.UUID) -> None:
        product = await self.products.get_by_id(product_id)
        if product is None:
            raise _not_found()
        await self.products.soft_delete(product)
        await self._cache_invalidate(product_id)
