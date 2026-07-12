"""All 9 endpoints. Routes stay thin — logic lives in product_service/queries."""

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_context import (
    ROLE_LEVEL,
    AuthContext,
    bearer_scheme,
    get_auth_context,
    require_role,
)
from app.database import engine, get_db, get_redis, redis_client
from app.product_service import ProductService, unique_slug
from app.queries import CategoryQuery, ProductQuery
from app.schemas import (
    CategoryCreate,
    CategoryOut,
    ProductCreate,
    ProductListResponse,
    ProductOut,
    ProductUpdate,
    StockDelta,
)

router = APIRouter()

CATEGORY_SLUG_MAX_LENGTH = 100


# ---------- products ----------

@router.get("/products", response_model=ProductListResponse)
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None, description="Category slug"),
    min_price: Decimal | None = Query(None, ge=0),
    max_price: Decimal | None = Query(None, ge=0),
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    # Soft-deleted products are admin-only: include_inactive requires an admin JWT
    if include_inactive:
        ctx = await get_auth_context(credentials)
        if ROLE_LEVEL.get(ctx.role, -1) < ROLE_LEVEL["admin"]:
            include_inactive = False

    products, total_count = await ProductQuery(db).list_products(
        page=page,
        page_size=page_size,
        category_slug=category,
        min_price=min_price,
        max_price=max_price,
        include_inactive=include_inactive,
    )
    return ProductListResponse(
        products=[ProductOut.model_validate(p) for p in products],
        total_count=total_count,
        page=page,
        page_size=page_size,
    )


@router.get("/products/{id_or_slug}")
async def get_product(
    id_or_slug: str,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    payload_json, cache_state = await ProductService(db, redis).get_cached(id_or_slug)
    return Response(
        content=payload_json,
        media_type="application/json",
        headers={"X-Cache": cache_state},
    )


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    body: ProductCreate,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    ctx: AuthContext = Depends(require_role("admin")),
):
    return await ProductService(db, redis).create(body, created_by=ctx.user_id)


@router.put("/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: uuid.UUID,
    body: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    _admin: AuthContext = Depends(require_role("admin")),
):
    return await ProductService(db, redis).update(product_id, body)


@router.patch("/products/{product_id}/stock", response_model=ProductOut)
async def change_stock(
    product_id: uuid.UUID,
    body: StockDelta,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    _admin: AuthContext = Depends(require_role("admin")),
):
    return await ProductService(db, redis).apply_stock_delta(product_id, body.delta)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    _admin: AuthContext = Depends(require_role("admin")),
):
    # Soft delete only — hard delete is not allowed (spec)
    await ProductService(db, redis).soft_delete(product_id)


# ---------- categories ----------

@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(db: AsyncSession = Depends(get_db)):
    return await CategoryQuery(db).list_all()


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    body: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    _admin: AuthContext = Depends(require_role("admin")),
):
    categories = CategoryQuery(db)
    if await categories.get_by_name(body.name) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A category with this name already exists",
        )
    slug = await unique_slug(body.name, categories.slug_exists, CATEGORY_SLUG_MAX_LENGTH)
    return await categories.create(name=body.name, slug=slug)


