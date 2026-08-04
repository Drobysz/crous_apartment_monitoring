"""End-to-end validation for the explicit Alembic migration chain.

Set MIGRATION_TEST_DATABASE_URL to a dedicated disposable PostgreSQL database.
This test intentionally destroys its schema; it never reads DATABASE_URL.
"""

import asyncio
import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.core.config import get_settings

pytestmark = pytest.mark.integration

BASE = "20260729_01_base"
ADMIN = "20260729_02_admin"
FILTERS = "20260729_03_filters"
HEAD = "20260804_07_favorites_reports"

EXPECTED_TABLES = {
    "admin_audits",
    "admin_notification_chats",
    "admin_sessions",
    "admins",
    "alembic_version",
    "geocoding_cache",
    "housing_daily_statistics",
    "housing_favorites",
    "image_cache",
    "listings",
    "notifications",
    "purchases",
    "search_display_groups",
    "search_display_messages",
    "search_listings",
    "searches",
    "favorite_restaurants",
    "favorite_availability_states",
    "favorite_transition_events",
    "restaurant_menu_deliveries",
    "restaurant_subscriptions",
    "subscription_plans",
    "user_subscriptions",
    "users",
    "user_platform_accounts",
    "user_reports",
}


def _migration_config() -> Config:
    return Config(str(Path(__file__).parents[2] / "alembic.ini"))


async def _schema_snapshot(
    database_url: str,
) -> tuple[set[str], set[str], set[str], list[tuple[str, int]], str | None]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync: set(inspect(sync).get_table_names())
            )
            search_columns = await connection.run_sync(
                lambda sync: {column["name"] for column in inspect(sync).get_columns("searches")}
            )
            user_columns = await connection.run_sync(
                lambda sync: {column["name"] for column in inspect(sync).get_columns("users")}
            )
            plans = (
                await connection.execute(
                    text("SELECT code, price_cents FROM subscription_plans ORDER BY code")
                )
            ).all()
            version = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
    finally:
        await engine.dispose()
    return table_names, search_columns, user_columns, plans, version


async def _table_names(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
    finally:
        await engine.dispose()


def test_full_migration_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.environ.get("MIGRATION_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("MIGRATION_TEST_DATABASE_URL is required for migration integration tests")

    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _migration_config()
    try:
        command.downgrade(config, "base")

        command.upgrade(config, BASE)
        tables, search_columns, user_columns, plans, version = asyncio.run(
            _schema_snapshot(database_url)
        )
        assert "searches" in tables
        assert "admins" not in tables
        assert "admin_notification_chats" not in tables
        assert "telegram_username" not in user_columns
        assert plans == [("lifetime", 2400), ("season", 1000)]
        assert version == BASE

        command.upgrade(config, ADMIN)
        tables, _, user_columns, _, version = asyncio.run(_schema_snapshot(database_url))
        assert {"admins", "admin_sessions", "admin_audits"} <= tables
        assert "admin_notification_chats" not in tables
        assert "telegram_username" not in user_columns
        assert version == ADMIN

        command.upgrade(config, FILTERS)
        tables, _, user_columns, _, version = asyncio.run(_schema_snapshot(database_url))
        assert "admin_notification_chats" not in tables
        assert "telegram_username" in user_columns
        assert version == FILTERS

        command.upgrade(config, HEAD)
        first_snapshot = asyncio.run(_schema_snapshot(database_url))
        tables, search_columns, _, plans, version = first_snapshot
        assert tables == EXPECTED_TABLES
        assert "last_changed_at" in search_columns
        assert plans == [("lifetime", 2400), ("season", 1000)]
        assert version == HEAD
        command.check(config)

        command.downgrade(config, FILTERS)
        assert "admin_notification_chats" not in asyncio.run(_table_names(database_url))
        command.downgrade(config, ADMIN)
        _, _, user_columns, _, version = asyncio.run(_schema_snapshot(database_url))
        assert "telegram_username" not in user_columns
        assert version == ADMIN
        command.downgrade(config, BASE)
        assert "admins" not in asyncio.run(_table_names(database_url))
        command.downgrade(config, "base")
        assert asyncio.run(_table_names(database_url)) == {"alembic_version"}

        command.upgrade(config, "head")
        assert asyncio.run(_schema_snapshot(database_url)) == first_snapshot
        command.upgrade(config, "head")
        assert asyncio.run(_schema_snapshot(database_url)) == first_snapshot
        command.check(config)
    finally:
        get_settings.cache_clear()
