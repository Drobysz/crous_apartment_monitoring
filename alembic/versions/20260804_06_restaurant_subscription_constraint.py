"""Remove the accidental restaurant primary-reference uniqueness.

Revision ID: 20260804_06_resto_constraint
Revises: 20260803_05_resto
Create Date: 2026-08-04
"""

from alembic import op

revision = "20260804_06_resto_constraint"
down_revision = "20260803_05_resto"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "restaurant_subscriptions_primary_restaurant_id_key"
INDEX_NAME = "ix_restaurant_subscriptions_primary_restaurant_id"
TABLE_NAME = "restaurant_subscriptions"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_="unique")
    op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
    op.create_index(INDEX_NAME, TABLE_NAME, ["primary_restaurant_id"])


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
    op.create_unique_constraint(CONSTRAINT_NAME, TABLE_NAME, ["primary_restaurant_id"])
    op.create_index(INDEX_NAME, TABLE_NAME, ["primary_restaurant_id"], unique=True)
