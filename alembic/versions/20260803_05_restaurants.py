"""Add restaurant subscriptions and immutable daily housing statistics.

Revision ID: 20260803_05_resto
Revises: 20260729_04_notify
Create Date: 2026-08-03
"""

import sqlalchemy as sa

from alembic import op

revision = "20260803_05_resto"
down_revision = "20260729_04_notify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "housing_daily_statistics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("search_id", sa.Integer(), nullable=False),
        sa.Column("search_identifier", sa.String(length=128), nullable=False),
        sa.Column("cheapest_price_cents", sa.Integer(), nullable=True),
        sa.Column("highest_price_cents", sa.Integer(), nullable=True),
        sa.Column("unique_apartment_count", sa.Integer(), nullable=False),
        sa.Column("statistic_date", sa.Date(), nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["search_id"], ["searches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "search_id", "statistic_date", name="uq_housing_daily_stat_search_date"
        ),
    )
    op.create_index("ix_housing_daily_statistics_user_id", "housing_daily_statistics", ["user_id"])
    op.create_index(
        "ix_housing_daily_statistics_search_id", "housing_daily_statistics", ["search_id"]
    )
    op.create_index(
        "ix_housing_daily_statistics_statistic_date", "housing_daily_statistics", ["statistic_date"]
    )
    op.create_table(
        "favorite_restaurants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("restaurant_code", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("city", sa.String(length=255), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "restaurant_code", name="uq_favorite_restaurant_user_code"),
    )
    op.create_index("ix_favorite_restaurants_user_id", "favorite_restaurants", ["user_id"])
    op.create_table(
        "restaurant_subscriptions",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("primary_restaurant_id", sa.Integer(), nullable=True),
        sa.Column("delivery_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("delivery_time", sa.Time(), nullable=False, server_default="08:00:00"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["primary_restaurant_id"], ["favorite_restaurants.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("primary_restaurant_id"),
    )
    op.create_index(
        "ix_restaurant_subscriptions_primary_restaurant_id",
        "restaurant_subscriptions",
        ["primary_restaurant_id"],
        unique=True,
    )
    op.create_table(
        "restaurant_menu_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("favorite_restaurant_id", sa.Integer(), nullable=True),
        sa.Column("delivery_date", sa.Date(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["favorite_restaurant_id"], ["favorite_restaurants.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "delivery_date", name="uq_restaurant_delivery_user_date"),
    )
    op.create_index(
        "ix_restaurant_menu_deliveries_user_id", "restaurant_menu_deliveries", ["user_id"]
    )
    op.create_index(
        "ix_restaurant_menu_deliveries_favorite_restaurant_id",
        "restaurant_menu_deliveries",
        ["favorite_restaurant_id"],
    )
    op.create_index(
        "ix_restaurant_menu_deliveries_delivery_date",
        "restaurant_menu_deliveries",
        ["delivery_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_restaurant_menu_deliveries_delivery_date", table_name="restaurant_menu_deliveries"
    )
    op.drop_index(
        "ix_restaurant_menu_deliveries_favorite_restaurant_id",
        table_name="restaurant_menu_deliveries",
    )
    op.drop_index("ix_restaurant_menu_deliveries_user_id", table_name="restaurant_menu_deliveries")
    op.drop_table("restaurant_menu_deliveries")
    op.drop_index(
        "ix_restaurant_subscriptions_primary_restaurant_id", table_name="restaurant_subscriptions"
    )
    op.drop_table("restaurant_subscriptions")
    op.drop_index("ix_favorite_restaurants_user_id", table_name="favorite_restaurants")
    op.drop_table("favorite_restaurants")
    op.drop_index(
        "ix_housing_daily_statistics_statistic_date", table_name="housing_daily_statistics"
    )
    op.drop_index("ix_housing_daily_statistics_search_id", table_name="housing_daily_statistics")
    op.drop_index("ix_housing_daily_statistics_user_id", table_name="housing_daily_statistics")
    op.drop_table("housing_daily_statistics")
