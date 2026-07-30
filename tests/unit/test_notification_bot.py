import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.admin.security import hash_password
from app.db.models import Admin, Base
from app.notification_bot.service import (
    active_notification_chat_ids,
    register_admin_notification_chat,
    telegram_username_handle,
)


@pytest.mark.asyncio
async def test_notification_chat_requires_active_admin_username() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        admin = Admin(
            name="Operations Lead",
            username="@gogona",
            username_key="gogona",
            password_hash=await hash_password("AsecurePassword9"),
            role="superadmin",
        )
        session.add(admin)
        await session.flush()
        assert not await register_admin_notification_chat(
            session,
            telegram_chat_id=123,
            telegram_user_id=123,
            telegram_username="guest",
        )
        telegram_username = telegram_username_handle("GoGoNa")
        assert telegram_username == "@gogona"
        assert await register_admin_notification_chat(
            session,
            telegram_chat_id=456,
            telegram_user_id=456,
            telegram_username=telegram_username,
        )
        assert await active_notification_chat_ids(session) == [456]
        admin.is_active = False
        await session.flush()
        assert await active_notification_chat_ids(session) == []
    await engine.dispose()
