import uuid
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Product


class CategoryQuery:
    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def get_by_id(self, category_id: uuid.UUID) -> Category | None:
        return await self.db_session.get(Category, category_id)

    async def get_by_name(self, name: str) -> Category | None:
        result = await self.db_session.execute(
            select(Category).where(Category.name == name)
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Category | None:
        result = await self.db_session.execute(
            select(Category).where(Category.slug == slug)
        )
        return result.scalar_one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        return await self.get_by_slug(slug) is not None

    async def list_all(self) -> list[Category]:
        result = await self.db_session.execute(
            select(Category).order_by(Category.name)
        )
        return list(result.scalars().all())

    async def create(self, name: str, slug: str) -> Category:
        category = Category(name=name, slug=slug)
        self.db_session.add(category)
        await self.db_session.commit()
        await self.db_session.refresh(category)
        return category


class ProductQuery:
    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def get_by_id(self, product_id: uuid.UUID) -> Product | None:
        return await self.db_session.get(Product, product_id)

    async def get_by_slug(self, slug: str) -> Product | None:
        result = await self.db_session.execute(
            select(Product).where(Product.slug == slug)
        )
        return result.scalar_one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        return await self.get_by_slug(slug) is not None

    async def create(self, **fields) -> Product:
        product = Product(**fields)
        self.db_session.add(product)
        await self.db_session.commit()
        await self.db_session.refresh(product)
        return product

    async def update_fields(self, product: Product, **fields) -> Product:
        for key, value in fields.items():
            setattr(product, key, value)
        await self.db_session.commit()
        await self.db_session.refresh(product)
        return product

    async def apply_stock_delta(
        self, product_id: uuid.UUID, delta: int
    ) -> Product | None:
        """Atomic stock change. The WHERE clause enforces the never-negative
        guard inside the database, so concurrent decrements can't oversell.
        Returns None if the guard rejected the change (or product is missing)."""
        result = await self.db_session.execute(
            update(Product)
            .where(
                Product.id == product_id,
                Product.stock_quantity + delta >= 0,
            )
            .values(stock_quantity=Product.stock_quantity + delta)
            .returning(Product)
        )
        product = result.scalar_one_or_none()
        await self.db_session.commit()
        return product

    async def soft_delete(self, product: Product) -> Product:
        product.is_active = False
        await self.db_session.commit()
        await self.db_session.refresh(product)
        return product

    async def list_products(
        self,
        page: int,
        page_size: int,
        category_slug: str | None = None,
        min_price: Decimal | None = None,
        max_price: Decimal | None = None,
        include_inactive: bool = False,
    ) -> tuple[list[Product], int]:
        filters = []
        if not include_inactive:
            filters.append(Product.is_active.is_(True))
        if category_slug is not None:
            filters.append(
                Product.category_id.in_(
                    select(Category.id).where(Category.slug == category_slug)
                )
            )
        if min_price is not None:
            filters.append(Product.price >= min_price)
        if max_price is not None:
            filters.append(Product.price <= max_price)

        total = await self.db_session.scalar(
            select(func.count()).select_from(Product).where(*filters)
        )
        result = await self.db_session.execute(
            select(Product)
            .where(*filters)
            .order_by(Product.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total or 0
