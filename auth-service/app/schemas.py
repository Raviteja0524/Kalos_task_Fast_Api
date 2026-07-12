"""All request/response shapes (Pydantic v2)."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import UserRole


# ---------- auth ----------

class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=100)
    password: str

    @field_validator("password")
    @classmethod
    def enforce_password_policy(cls, value: str) -> str:
        # Spec: minimum 8 characters, at least one uppercase, one number
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", value):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"\d", value):
            raise ValueError("Password must contain at least one number")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# ---------- users ----------

class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    is_verified: bool
    last_login_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UpdateMeRequest(BaseModel):
    # Spec: PATCH /auth/me updates full_name only (email changes out of scope)
    full_name: str = Field(min_length=1, max_length=100)


class RoleUpdateRequest(BaseModel):
    role: UserRole


class UserListResponse(BaseModel):
    users: list[UserOut]
    total_count: int
    page: int
    page_size: int
