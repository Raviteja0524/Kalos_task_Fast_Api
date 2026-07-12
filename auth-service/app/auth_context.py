
import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_service import decode_token
from app.database import get_db
from app.models import ROLE_LEVEL, User, UserRole
from app.queries import UserQuery


class AuthContext:
    def __init__(self, user_id: str, email: str, role: str):
        self.user_id = user_id
        self.email = email
        self.role = role


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


# Declared as a security scheme so Swagger UI shows the Authorize button
# and sends the token with every request. auto_error=False so WE control
# the error response (401 instead of FastAPI's default 403).
bearer_scheme = HTTPBearer(auto_error=False)


async def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthContext:
    if credentials is None:
        raise _unauthorized("Missing or invalid Authorization header")
    token = credentials.credentials

    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token has expired")
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid token")

    # A refresh token is NOT a door pass — only access tokens get in here
    if payload.get("type") != "access":
        raise _unauthorized("Invalid token type")

    return AuthContext(
        user_id=payload["sub"],
        email=payload["email"],
        role=payload["role"],
    )


async def get_current_user(
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await UserQuery(db).get_user_by_id(uuid.UUID(ctx.user_id))
    if user is None:
        raise _unauthorized("User no longer exists")
    if not user.is_active:
        # Spec: is_active=false returns 403 on all authenticated endpoints
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is disabled"
        )
    return user


def require_role(min_role: UserRole):
    """Dependency factory: require_role(UserRole.admin) lets admin and
    super_admin through, and 403s everyone below."""

    async def checker(user: User = Depends(get_current_user)) -> User:
        if ROLE_LEVEL[user.role] < ROLE_LEVEL[min_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return checker
