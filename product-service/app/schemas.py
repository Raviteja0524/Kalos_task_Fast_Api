"""All request/response shapes (Pydantic v2)."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# ---------- categories ----------

class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------- products ----------

class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    stock_quantity: int = Field(default=0, ge=0)
    category_id: uuid.UUID


class ProductUpdate(BaseModel):
    """PUT /products/{id} — full update. stock_quantity is deliberately
    excluded: stock changes go through PATCH /products/{id}/stock (delta)."""

    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    category_id: uuid.UUID
    is_active: bool = True


class StockDelta(BaseModel):
    delta: int  # positive adds stock, negative reduces it


class ProductOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    price: Decimal
    stock_quantity: int
    category_id: uuid.UUID
    is_active: bool
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductListResponse(BaseModel):
    products: list[ProductOut]
    total_count: int
    page: int
    page_size: int
