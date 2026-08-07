"""Register notification chats only after active-admin username verification.

Revision ID: 20260729_04_notify
Revises: 20260729_03_filters
Create Date: 2026-07-29
"""

import sqlalchemy as sa

from alembic import op

revision = "20260729_04_notify"
down_revision = "20260729_03_filters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_notification_chats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admins.id"],
            name="fk_admin_notification_chats_admin_id_admins",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_notification_chats"),
    )
    op.create_index(
        "ix_admin_notification_chats_admin_id",
        "admin_notification_chats",
        ["admin_id"],
        unique=True,
    )
    op.create_index(
        "ix_admin_notification_chats_telegram_user_id",
        "admin_notification_chats",
        ["telegram_user_id"],
        unique=True,
    )
    op.create_index(
        "ix_admin_notification_chats_telegram_chat_id",
        "admin_notification_chats",
        ["telegram_chat_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admin_notification_chats_telegram_chat_id", table_name="admin_notification_chats"
    )
    op.drop_index(
        "ix_admin_notification_chats_telegram_user_id", table_name="admin_notification_chats"
    )
    op.drop_index("ix_admin_notification_chats_admin_id", table_name="admin_notification_chats")
    op.drop_table("admin_notification_chats")
