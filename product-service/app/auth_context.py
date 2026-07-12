"""JWT validation with the shared Auth Service secret.

Spec: decode and verify the token only — NO call to the Auth Service or its DB.
Everything we know about the caller comes from the token claims.
"""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

# Role hierarchy: higher number = more power
ROLE_LEVEL = {"customer": 0, "admin": 1, "super_admin": 2}


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


def decode_token(token: str) -> dict:
    # algorithms must be pinned explicitly — never trust the token's own header
    return jwt.decode(
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )


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

    if payload.get("type") != "access":
        raise _unauthorized("Invalid token type")

    return AuthContext(
        user_id=payload["sub"],
        email=payload["email"],
        role=payload["role"],
    )


def require_role(min_role: str):
    """Dependency factory: require_role("admin") lets admin and super_admin
    through, and 403s everyone below."""

    async def checker(
        ctx: AuthContext = Depends(get_auth_context),
    ) -> AuthContext:
        if ROLE_LEVEL.get(ctx.role, -1) < ROLE_LEVEL[min_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return ctx

    return checker
