import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api_main import app
from app.core.config import Settings, get_settings
from app.db.models import Base, ReferralOwnerLoginToken, ReferralProgram
from app.db.session import get_session
from app.referral_bot.main import dashboard_link, dashboard_url
from app.referrals.service import issue_owner_login_token


@pytest.mark.asyncio
async def test_owner_token_exchange_uses_single_use_cookie_session_and_scopes_data() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    settings = Settings(
        admin_session_secret="test-owner-session-secret-with-sufficient-length",
        referral_stats_base_url="http://localhost",
        test_mode=True,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        owner_a = ReferralProgram(
            referral_code="owner-a",
            owner_telegram_username="@owner_a",
            owner_username_key="owner_a",
            owner_telegram_user_id=101,
            commission_rate_basis_points=3000,
        )
        owner_b = ReferralProgram(
            referral_code="owner-b",
            owner_telegram_username="@owner_b",
            owner_username_key="owner_b",
            owner_telegram_user_id=202,
            commission_rate_basis_points=3000,
        )
        session.add_all((owner_a, owner_b))
        await session.flush()
        raw_token = await issue_owner_login_token(session, owner_a, ttl_minutes=15)
        await session.commit()
        token_row = await session.scalar(
            select(ReferralOwnerLoginToken).where(
                ReferralOwnerLoginToken.referral_program_id == owner_a.id
            )
        )
        assert token_row is not None and token_row.token_hash != raw_token

    async def session_override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as anonymous:
            assert (await anonymous.get("/referral-owner/me")).status_code == 401
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            exchange = await client.post("/referral-owner/auth/exchange", json={"token": raw_token})
            assert exchange.status_code == 200
            assert "access_token" not in exchange.json()
            assert client.cookies.get("crous_referral_owner_session")
            assert (
                await client.post("/referral-owner/auth/exchange", json={"token": raw_token})
            ).status_code == 401
            assert (
                await client.post("/referral-owner/auth/exchange", json={"token": "x" * 32})
            ).status_code == 401
            assert (await client.get("/referral-owner/me")).json()["referral_code"] == "owner-a"
            stats = await client.get(f"/referral-owner/stats?referral_id={owner_b.id}")
            assert stats.status_code == 200
            assert stats.json()["attached_users"] == 0
            assert (await client.get("/referral-owner/purchases")).status_code == 200
        async with factory() as session:
            used = await session.scalar(
                select(ReferralOwnerLoginToken).where(
                    ReferralOwnerLoginToken.token_hash == token_row.token_hash
                )
            )
            assert used is not None and used.used_at is not None
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


def test_referral_bot_renders_localized_statistics_hyperlink() -> None:
    url = dashboard_url("https://stats.example", "token-value")
    message = dashboard_link("ru", url)
    assert (
        message
        == '<a href="https://stats.example/referral/dashboard?token=token-value">Ваша статистика по рефералам</a>'
    )
    assert "Lifetime" not in message
