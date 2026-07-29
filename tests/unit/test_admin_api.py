import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.admin.security import hash_password
from app.api_main import app
from app.core.config import Settings, get_settings
from app.db.models import Admin, Base
from app.db.session import get_session


@pytest.mark.asyncio
async def test_superadmin_can_create_an_admin_through_the_protected_api() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    settings = Settings(admin_session_secret="test-admin-session-secret-with-sufficient-length")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(
            Admin(
                name="Operations Lead",
                username="@gogona",
                username_key="gogona",
                password_hash=await hash_password("AsecurePassword9"),
                role="superadmin",
            )
        )
        await session.commit()

    async def session_override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            login = await client.post(
                "/admin/auth/login",
                json={"username": "gogona", "password": "AsecurePassword9"},
                headers={"Origin": "http://localhost"},
            )
            assert login.status_code == 200
            assert login.json()["admin"]["role"] == "superadmin"
            me = await client.get("/admin/me")
            assert me.status_code == 200
            dashboard = await client.get("/admin/dashboard?period=month")
            assert dashboard.status_code == 200
            assert dashboard.json()["total_users"] == 0
            created = await client.post(
                "/admin/admins",
                json={"name": "Nadia Martin", "username": "@nadia_ops", "password": "AnotherSecure9", "role": "admin"},
                headers={"Origin": "http://localhost", "X-CSRF-Token": client.cookies.get("crous_admin_csrf")},
            )
            assert created.status_code == 201
            assert created.json()["username"] == "@nadia_ops"
            protected = await client.patch(
                f"/admin/admins/{me.json()['id']}",
                json={"is_active": False},
                headers={"Origin": "http://localhost", "X-CSRF-Token": client.cookies.get("crous_admin_csrf")},
            )
            assert protected.status_code == 409
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
