"""Replace per-search intervals and one-off notifications with display snapshots.

Revision ID: 0003_snapshot_display_groups
Revises: 0002_telegram_ids_bigint
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_snapshot_display_groups"
down_revision = "0002_telegram_ids_bigint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("searches", sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("searches", sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=True))
    op.drop_index("ix_searches_next_check_at", table_name="searches")
    op.drop_column("searches", "next_check_at")
    op.drop_column("searches", "check_interval_minutes")
    op.drop_column("searches", "is_initialized")
    op.create_table(
        "search_display_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("search_id", sa.Integer(), sa.ForeignKey("searches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("listing_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_search_display_groups_search_id", "search_display_groups", ["search_id"])
    op.create_index("ix_search_display_groups_fingerprint", "search_display_groups", ["fingerprint"])
    op.create_index("ix_search_display_groups_status", "search_display_groups", ["status"])
    op.create_table(
        "search_display_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("display_group_id", sa.Integer(), sa.ForeignKey("search_display_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("message_kind", sa.String(length=16), nullable=False, server_default="card"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("display_group_id", "telegram_message_id", name="uq_display_message"),
    )
    op.create_index("ix_search_display_messages_display_group_id", "search_display_messages", ["display_group_id"])


def downgrade() -> None:
    op.drop_index("ix_search_display_messages_display_group_id", table_name="search_display_messages")
    op.drop_table("search_display_messages")
    op.drop_index("ix_search_display_groups_status", table_name="search_display_groups")
    op.drop_index("ix_search_display_groups_fingerprint", table_name="search_display_groups")
    op.drop_index("ix_search_display_groups_search_id", table_name="search_display_groups")
    op.drop_table("search_display_groups")
    op.add_column("searches", sa.Column("is_initialized", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("searches", sa.Column("check_interval_minutes", sa.Integer(), nullable=False, server_default="120"))
    op.add_column("searches", sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_searches_next_check_at", "searches", ["next_check_at"])
    op.drop_column("searches", "snapshot_fingerprint")
    op.drop_column("searches", "last_changed_at")
