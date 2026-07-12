import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserRole


class UserQuery:
    """All DB access for users. Routes never write queries themselves."""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self.db_session.execute(
            select(User).where(User.email == email.lower())
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.db_session.get(User, user_id)

    async def create_user(self, email: str, full_name: str, hashed_password: str) -> User:
        user = User(
            email=email.lower(),  # spec: emails are lowercased on insert
            full_name=full_name,
            hashed_password=hashed_password,
        )
        self.db_session.add(user)
        await self.db_session.commit()
        await self.db_session.refresh(user)
        return user

    async def update_full_name(self, user: User, full_name: str) -> User:
        user.full_name = full_name
        await self.db_session.commit()
        await self.db_session.refresh(user)
        return user

    async def update_last_login(self, user: User, at: datetime) -> None:
        user.last_login_at = at
        await self.db_session.commit()

    async def update_role(self, user_id: uuid.UUID, role: UserRole) -> User | None:
        user = await self.get_user_by_id(user_id)
        if user is None:
            return None
        user.role = role
        await self.db_session.commit()
        await self.db_session.refresh(user)
        return user

    async def list_users(
        self, page: int = 1, page_size: int = 20
    ) -> tuple[list[User], int]:
        total = await self.db_session.scalar(select(func.count()).select_from(User))
        result = await self.db_session.execute(
            select(User)
            .order_by(User.created_at)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total or 0
