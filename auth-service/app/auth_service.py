"""All auth logic in one place: password hashing, JWT mint/verify,
register/login/refresh/logout, rate limiting.

Refresh tokens: each carries a jti stored in Redis (refresh:{jti}, 7-day TTL).
Rotation and logout delete the key — that is the revocation.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, status
from passlib.context import CryptContext
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import User
from app.queries import UserQuery
from app.schemas import TokenPair

# Spec: bcrypt with minimum cost factor 12
pwd_context = CryptContext(schemes=["bcrypt"], bcrypt__rounds=12)

REFRESH_KEY = "refresh:{jti}"
FAIL_KEY = "login_fail:{email}"
FAILED_LOGIN_LIMIT = 5
FAILED_LOGIN_WINDOW_SECONDS = 15 * 60


# ---------- passwords ----------

def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ---------- tokens ----------

def create_access_token(user_id: uuid.UUID | str, email: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(user_id),  # PyJWT requires sub to be a string
        "email": email,
        "role": role,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: uuid.UUID | str) -> tuple[str, str]:
    """Returns (token, jti)."""
    jti = str(uuid.uuid4())
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "type": "refresh",
        "exp": expire,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti


def decode_token(token: str) -> dict:
    # algorithms must be pinned explicitly — never trust the token's own header
    return jwt.decode(
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


# ---------- the service ----------

class AuthService:
    def __init__(self, db: AsyncSession, redis: Redis):
        self.users = UserQuery(db)
        self.redis = redis

    async def issue_pair(self, user: User) -> TokenPair:
        access_token = create_access_token(user.id, user.email, user.role.value)
        refresh_token, jti = create_refresh_token(user.id)
        ttl_seconds = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
        await self.redis.set(REFRESH_KEY.format(jti=jti), str(user.id), ex=ttl_seconds)
        return TokenPair(access_token=access_token, refresh_token=refresh_token)

    async def register(self, email: str, full_name: str, password: str) -> User:
        if await self.users.get_user_by_email(email) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists",
            )
        return await self.users.create_user(
            email=email,
            full_name=full_name,
            hashed_password=hash_password(password),
        )

    async def login(self, email: str, password: str, client_ip: str) -> TokenPair:
        email = email.lower()
        fail_key = FAIL_KEY.format(email=email)

        # Spec: 5 failed attempts per email within 15 minutes -> 429
        failures = await self.redis.get(fail_key)
        if failures is not None and int(failures) >= FAILED_LOGIN_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed login attempts. Try again in 15 minutes.",
            )

        user = await self.users.get_user_by_email(email)
        if user is None or not verify_password(password, user.hashed_password):
            count = await self.redis.incr(fail_key)
            if count == 1:
                await self.redis.expire(fail_key, FAILED_LOGIN_WINDOW_SECONDS)
            # Same message for unknown email and wrong password — don't leak which
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="User account is disabled"
            )

        await self.redis.delete(fail_key)
        await self.users.update_last_login(user, datetime.now(timezone.utc))
        return await self.issue_pair(user)

    def _decode_refresh(self, refresh_token: str) -> dict:
        try:
            payload = decode_token(refresh_token)
        except jwt.ExpiredSignatureError:
            raise _unauthorized("Refresh token has expired")
        except jwt.InvalidTokenError:
            raise _unauthorized("Invalid refresh token")
        if payload.get("type") != "refresh":
            raise _unauthorized("Invalid token type")
        return payload

    async def refresh(self, refresh_token: str) -> TokenPair:
        payload = self._decode_refresh(refresh_token)
        # GETDEL is atomic: two concurrent refreshes can't both succeed (rotation)
        user_id = await self.redis.getdel(REFRESH_KEY.format(jti=payload["jti"]))
        if user_id is None:
            raise _unauthorized("Refresh token is no longer valid")

        user = await self.users.get_user_by_id(uuid.UUID(user_id))
        if user is None:
            raise _unauthorized("User no longer exists")
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="User account is disabled"
            )
        return await self.issue_pair(user)

    async def logout(self, refresh_token: str) -> None:
        """Blacklist the refresh token by removing its Redis entry."""
        payload = self._decode_refresh(refresh_token)
        await self.redis.delete(REFRESH_KEY.format(jti=payload["jti"]))
