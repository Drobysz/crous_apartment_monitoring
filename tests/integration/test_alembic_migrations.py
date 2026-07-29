"""Round-trip validation for the explicit Alembic baseline.

Set MIGRATION_TEST_DATABASE_URL to a dedicated disposable PostgreSQL database.
The test intentionally performs a destructive downgrade to prove the baseline
can be recreated; it never reads DATABASE_URL.
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

EXPECTED_TABLES = {
    "admin_audits",
    "admin_notification_chats",
    "admin_sessions",
    "admins",
    "alembic_version",
    "geocoding_cache",
    "image_cache",
    "listings",
    "notifications",
    "purchases",
    "search_display_groups",
    "search_display_messages",
    "search_listings",
    "searches",
    "subscription_plans",
    "user_subscriptions",
    "users",
}


def _migration_config() -> Config:
    return Config(str(Path(__file__).parents[2] / "alembic.ini"))


async def _schema_snapshot(database_url: str) -> tuple[set[str], list[str], list[tuple[str, int]]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            table_names = await connection.run_sync(lambda sync_connection: set(inspect(sync_connection).get_table_names()))
            columns = await connection.run_sync(
                lambda sync_connection: [
                    column["name"] for column in inspect(sync_connection).get_columns("searches")
                ]
            )
            plans = (await connection.execute(text("SELECT code, price_cents FROM subscription_plans ORDER BY code"))).all()
    finally:
        await engine.dispose()
    return table_names, columns, plans


async def _table_names(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(lambda sync_connection: set(inspect(sync_connection).get_table_names()))
    finally:
        await engine.dispose()


def test_baseline_upgrade_downgrade_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.environ.get("MIGRATION_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("MIGRATION_TEST_DATABASE_URL is required for migration integration tests")

    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _migration_config()
    try:
        command.upgrade(config, "head")
        tables, search_columns, plans = asyncio.run(_schema_snapshot(database_url))
        assert EXPECTED_TABLES == tables
        assert search_columns.count("last_changed_at") == 1
        assert plans == [("lifetime", 2400), ("season", 1000)]

        command.downgrade(config, "base")
        assert asyncio.run(_table_names(database_url)) == {"alembic_version"}

        command.upgrade(config, "head")
        tables, search_columns, plans = asyncio.run(_schema_snapshot(database_url))
        assert EXPECTED_TABLES == tables
        assert search_columns.count("last_changed_at") == 1
        assert plans == [("lifetime", 2400), ("season", 1000)]
    finally:
        get_settings.cache_clear()
