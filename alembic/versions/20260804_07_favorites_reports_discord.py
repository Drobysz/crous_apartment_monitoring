"""Add housing favourites, favourite transition outbox, reports and platform accounts.

Revision ID: 20260804_07_favorites_reports
Revises: 20260804_06_resto_constraint
Create Date: 2026-08-04
"""

import sqlalchemy as sa

from alembic import op

revision = "20260804_07_favorites_reports"
down_revision = "20260804_06_resto_constraint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("users", "telegram_user_id", existing_type=sa.BigInteger(), nullable=True)
    op.alter_column("users", "telegram_chat_id", existing_type=sa.BigInteger(), nullable=True)
    op.create_table(
        "housing_favorites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "listing_id", name="uq_housing_favorite_user_listing"),
    )
    op.create_index("ix_housing_favorites_user_id", "housing_favorites", ["user_id"])
    op.create_index("ix_housing_favorites_listing_id", "housing_favorites", ["listing_id"])
    op.create_table(
        "user_platform_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("platform_user_id", sa.BigInteger(), nullable=False),
        sa.Column("platform_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("platform_username", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "platform_user_id", name="uq_user_platform_account"),
    )
    op.create_index("ix_user_platform_accounts_user_id", "user_platform_accounts", ["user_id"])
    op.create_index(
        "ix_user_platform_accounts_platform_username",
        "user_platform_accounts",
        ["platform_username"],
    )
    op.execute(
        "INSERT INTO user_platform_accounts (user_id, platform, platform_user_id, platform_chat_id, platform_username) "
        "SELECT id, 'telegram', telegram_user_id, telegram_chat_id, telegram_username FROM users"
    )
    op.create_table(
        "favorite_availability_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("favorite_id", sa.Integer(), nullable=False),
        sa.Column("search_id", sa.Integer(), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.Column("transition_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["favorite_id"], ["housing_favorites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["search_id"], ["searches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("favorite_id", "search_id", name="uq_favorite_availability_search"),
    )
    op.create_index(
        "ix_favorite_availability_states_favorite_id",
        "favorite_availability_states",
        ["favorite_id"],
    )
    op.create_index(
        "ix_favorite_availability_states_search_id", "favorite_availability_states", ["search_id"]
    )
    op.create_table(
        "favorite_transition_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("availability_state_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("transition", sa.String(length=16), nullable=False),
        sa.Column("transition_sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["availability_state_id"], ["favorite_availability_states.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "availability_state_id", "transition_sequence", name="uq_favorite_transition_sequence"
        ),
    )
    op.create_index(
        "ix_favorite_transition_events_availability_state_id",
        "favorite_transition_events",
        ["availability_state_id"],
    )
    op.create_index(
        "ix_favorite_transition_events_user_id", "favorite_transition_events", ["user_id"]
    )
    op.create_index(
        "ix_favorite_transition_events_listing_id", "favorite_transition_events", ["listing_id"]
    )
    op.create_index(
        "ix_favorite_transition_events_status", "favorite_transition_events", ["status"]
    )
    op.create_table(
        "user_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("platform_account_id", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["platform_account_id"], ["user_platform_accounts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_reports_user_id", "user_reports", ["user_id"])
    op.create_index("ix_user_reports_platform_account_id", "user_reports", ["platform_account_id"])
    op.create_index("ix_user_reports_created_at", "user_reports", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_user_reports_created_at", table_name="user_reports")
    op.drop_index("ix_user_reports_platform_account_id", table_name="user_reports")
    op.drop_index("ix_user_reports_user_id", table_name="user_reports")
    op.drop_table("user_reports")
    op.drop_index("ix_favorite_transition_events_status", table_name="favorite_transition_events")
    op.drop_index(
        "ix_favorite_transition_events_listing_id", table_name="favorite_transition_events"
    )
    op.drop_index("ix_favorite_transition_events_user_id", table_name="favorite_transition_events")
    op.drop_index(
        "ix_favorite_transition_events_availability_state_id",
        table_name="favorite_transition_events",
    )
    op.drop_table("favorite_transition_events")
    op.drop_index(
        "ix_favorite_availability_states_search_id", table_name="favorite_availability_states"
    )
    op.drop_index(
        "ix_favorite_availability_states_favorite_id", table_name="favorite_availability_states"
    )
    op.drop_table("favorite_availability_states")
    op.drop_index(
        "ix_user_platform_accounts_platform_username", table_name="user_platform_accounts"
    )
    op.drop_index("ix_user_platform_accounts_user_id", table_name="user_platform_accounts")
    op.drop_table("user_platform_accounts")
    op.drop_index("ix_housing_favorites_listing_id", table_name="housing_favorites")
    op.drop_index("ix_housing_favorites_user_id", table_name="housing_favorites")
    op.drop_table("housing_favorites")
    # Discord-only accounts cannot be represented by the legacy Telegram-only
    # schema, so an operator must remove or backfill them before this downgrade.
    op.alter_column("users", "telegram_chat_id", existing_type=sa.BigInteger(), nullable=False)
    op.alter_column("users", "telegram_user_id", existing_type=sa.BigInteger(), nullable=False)
