"""Persist Telegram usernames and normalize legacy accommodation-format codes.

Revision ID: 20260729_03_filters
Revises: 20260729_02_admin
Create Date: 2026-07-29
"""

import sqlalchemy as sa

from alembic import op

revision = "20260729_03_filters"
down_revision = "20260729_02_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_username", sa.String(length=32), nullable=True))
    op.create_index("ix_users_telegram_username", "users", ["telegram_username"])
    op.execute("UPDATE searches SET accommodation_format = 'individual' WHERE accommodation_format = 'individuel'")


def downgrade() -> None:
    op.execute("UPDATE searches SET accommodation_format = 'individuel' WHERE accommodation_format = 'individual'")
    op.drop_index("ix_users_telegram_username", table_name="users")
    op.drop_column("users", "telegram_username")
