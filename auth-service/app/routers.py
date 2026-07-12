"""All 9 endpoints. Routes stay thin — logic lives in auth_service/queries."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_context import get_current_user, require_role
from app.auth_service import AuthService
from app.database import engine, get_db, get_redis, redis_client
from app.models import User, UserRole
from app.queries import UserQuery
from app.schemas import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    RoleUpdateRequest,
    TokenPair,
    UpdateMeRequest,
    UserListResponse,
    UserOut,
)

router = APIRouter()


# ---------- public ----------

@router.post("/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    return await AuthService(db, redis).register(
        email=body.email, full_name=body.full_name, password=body.password
    )


@router.post("/auth/login", response_model=TokenPair)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    client_ip = request.client.host if request.client else "unknown"
    return await AuthService(db, redis).login(
        email=body.email, password=body.password, client_ip=client_ip
    )


@router.post("/auth/refresh", response_model=TokenPair)
async def refresh(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    return await AuthService(db, redis).refresh(body.refresh_token)


# ---------- JWT-protected ----------

@router.post("/auth/logout")
async def logout(
    body: LogoutRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    await AuthService(db, redis).logout(body.refresh_token)
    return {"detail": "Logged out successfully"}


@router.get("/auth/me", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user)):
    return user


@router.patch("/auth/me", response_model=UserOut)
async def update_me(
    body: UpdateMeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await UserQuery(db).update_full_name(user, body.full_name)


# ---------- admin ----------

@router.get("/auth/users", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
):
    users, total_count = await UserQuery(db).list_users(page=page, page_size=page_size)
    return UserListResponse(
        users=[UserOut.model_validate(user) for user in users],
        total_count=total_count,
        page=page,
        page_size=page_size,
    )


@router.patch("/auth/users/{user_id}/role", response_model=UserOut)
async def update_user_role(
    user_id: uuid.UUID,
    body: RoleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _super_admin: User = Depends(require_role(UserRole.super_admin)),
):
    user = await UserQuery(db).update_role(user_id, body.role)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user


# ---------- health ----------

# @router.get("/health")
# async def health_check():
#     db_status = "up"
#     try:
#         async with engine.connect() as conn:
#             await conn.execute(text("SELECT 1"))
#     except Exception:
#         db_status = "down"

#     redis_status = "up"
#     try:
#         await redis_client.ping()
#     except Exception:
#         redis_status = "down"

#     healthy = db_status == "up" and redis_status == "up"
#     return {
#         "status": "healthy" if healthy else "degraded",
#         "database": db_status,
#         "redis": redis_status,
#     }
