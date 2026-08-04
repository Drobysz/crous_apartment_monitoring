"""Add non-destructive referral program deletion metadata.

Revision ID: 20260804_09_referral_soft_delete
Revises: 20260804_08_referrals
"""

import sqlalchemy as sa

from alembic import op

revision = "20260804_09_referral_soft_delete"
down_revision = "20260804_08_referrals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("referral_programs", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("referral_programs", sa.Column("deleted_by_admin_id", sa.Integer()))
    op.create_foreign_key(
        "fk_referral_programs_deleted_by_admin_id_admins",
        "referral_programs",
        "admins",
        ["deleted_by_admin_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_referral_programs_deleted_at", "referral_programs", ["deleted_at"])
    op.create_index(
        "ix_referral_programs_deleted_by_admin_id", "referral_programs", ["deleted_by_admin_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_referral_programs_deleted_by_admin_id", table_name="referral_programs")
    op.drop_index("ix_referral_programs_deleted_at", table_name="referral_programs")
    op.drop_constraint(
        "fk_referral_programs_deleted_by_admin_id_admins", "referral_programs", type_="foreignkey"
    )
    op.drop_column("referral_programs", "deleted_by_admin_id")
    op.drop_column("referral_programs", "deleted_at")
