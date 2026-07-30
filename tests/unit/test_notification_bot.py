import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.admin.security import hash_password
from app.core.config import Settings
from app.db.models import Admin, Base
from app.notification_bot.main import configure_webhook
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


@pytest.mark.asyncio
async def test_notification_bot_registers_its_webhook_in_webhook_mode() -> None:
    calls: list[tuple[str, str]] = []

    class FakeBot:
        async def set_webhook(self, url: str, *, secret_token: str) -> None:
            calls.append((url, secret_token))

    settings = Settings(
        run_mode="webhook",
        public_base_url="https://bot.example.test",
        notification_webhook_secret="notification-secret",
    )
    await configure_webhook(FakeBot(), settings)  # type: ignore[arg-type]

    assert calls == [("https://bot.example.test/notification_bot/webhook", "notification-secret")]
