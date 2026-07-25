"""Store Telegram identifiers without the signed 32-bit limit.

Revision ID: 0002_telegram_ids_bigint
Revises: 0001_initial
"""

from sqlalchemy import BigInteger, Integer

from alembic import op


revision = "0002_telegram_ids_bigint"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        "telegram_user_id",
        "telegram_chat_id",
        "active_navigation_chat_id",
    ):
        op.alter_column(
            "users",
            column,
            existing_type=Integer(),
            type_=BigInteger(),
            postgresql_using=f"{column}::bigint",
        )


def downgrade() -> None:
    for column in (
        "telegram_user_id",
        "telegram_chat_id",
        "active_navigation_chat_id",
    ):
        op.alter_column(
            "users",
            column,
            existing_type=BigInteger(),
            type_=Integer(),
            postgresql_using=f"{column}::integer",
        )
