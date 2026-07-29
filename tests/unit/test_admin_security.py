import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.admin.security import (
    AuthenticationError,
    PasswordPolicyError,
    create_session,
    decode_access_token,
    hash_password,
    normalize_username,
    resolve_principal,
    rotate_session,
    validate_password,
)
from app.core.config import Settings
from app.db.models import Admin, Base, User


def test_username_normalization_and_password_policy() -> None:
    assert normalize_username(" @GoGoNa ") == ("@gogona", "gogona")
    with pytest.raises(ValueError):
        normalize_username("not valid")
    with pytest.raises(PasswordPolicyError):
        validate_password("short")


@pytest.mark.asyncio
async def test_admin_sessions_are_signed_rotated_and_bound_to_an_active_admin() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    settings = Settings(admin_session_secret="test-admin-session-secret-with-sufficient-length")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        password_hash = await hash_password("AsecurePassword9")
        admin = Admin(name="Operations", username="@gogona", username_key="gogona", password_hash=password_hash, role="superadmin")
        session.add_all((admin, User(telegram_user_id=99, telegram_chat_id=99, language="en")))
        await session.flush()
        tokens = await create_session(session, admin, settings)
        claims = decode_access_token(tokens.access_token, settings)
        assert claims["sub"] == str(admin.id)
        principal = await resolve_principal(session, tokens.access_token, settings)
        assert principal.role == "superadmin"
        _, rotated = await rotate_session(session, tokens.refresh_token, settings)
        assert rotated.refresh_token != tokens.refresh_token
        with pytest.raises(AuthenticationError):
            await rotate_session(session, tokens.refresh_token, settings)
    await engine.dispose()
