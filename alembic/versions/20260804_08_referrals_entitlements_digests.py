"""Add referral accounting, owner-login and promotional-digest persistence.

Revision ID: 20260804_08_referrals
Revises: 20260804_07_favorites_reports
Create Date: 2026-08-04

Downgrade removes referral and digest records. Operators must reconcile paid
manual transfers before downgrading because external transfers cannot be undone.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260804_08_referrals"
down_revision = "20260804_07_favorites_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("digest_opted_out", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "referral_programs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("referral_code", sa.String(length=64), nullable=False),
        sa.Column("owner_telegram_username", sa.String(length=33), nullable=False),
        sa.Column("owner_username_key", sa.String(length=32), nullable=False),
        sa.Column("owner_telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "commission_rate_basis_points", sa.Integer(), nullable=False, server_default="3000"
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_admin_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "commission_rate_basis_points >= 0 AND commission_rate_basis_points <= 10000",
            name="ck_referral_program_rate",
        ),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("referral_code"),
        sa.UniqueConstraint("owner_telegram_user_id"),
    )
    op.create_index("ix_referral_programs_referral_code", "referral_programs", ["referral_code"])
    op.create_index(
        "ix_referral_programs_owner_username_key", "referral_programs", ["owner_username_key"]
    )
    op.create_index(
        "ix_referral_programs_owner_telegram_user_id",
        "referral_programs",
        ["owner_telegram_user_id"],
    )
    op.create_index("ix_referral_programs_is_active", "referral_programs", ["is_active"])
    op.create_index(
        "ix_referral_programs_created_by_admin_id", "referral_programs", ["created_by_admin_id"]
    )
    op.create_table(
        "user_referrals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("referral_program_id", sa.Integer(), nullable=False),
        sa.Column(
            "attributed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "attribution_source",
            sa.String(length=32),
            nullable=False,
            server_default="telegram_start",
        ),
        sa.ForeignKeyConstraint(
            ["referral_program_id"], ["referral_programs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_referral_user"),
    )
    op.create_index(
        "ix_user_referrals_referral_program_id", "user_referrals", ["referral_program_id"]
    )
    op.create_table(
        "referral_commissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("referral_program_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purchase_id", sa.Integer(), nullable=True),
        sa.Column("payment_event_id", sa.String(length=255), nullable=True),
        sa.Column("gross_amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
        sa.Column("commission_rate_basis_points", sa.Integer(), nullable=False),
        sa.Column("commission_amount_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="earned"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversal_of_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("gross_amount_cents >= 0", name="ck_referral_commission_gross"),
        sa.CheckConstraint("commission_amount_cents >= 0", name="ck_referral_commission_amount"),
        sa.CheckConstraint("currency = 'EUR'", name="ck_referral_commission_currency"),
        sa.CheckConstraint(
            "status IN ('pending', 'earned', 'reversed', 'paid')",
            name="ck_referral_commission_status",
        ),
        sa.ForeignKeyConstraint(
            ["referral_program_id"], ["referral_programs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_id"], ["purchases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["reversal_of_id"], ["referral_commissions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("purchase_id", name="uq_referral_commission_purchase"),
        sa.UniqueConstraint("payment_event_id", name="uq_referral_commission_payment_event"),
        sa.UniqueConstraint("reversal_of_id", name="uq_referral_commission_reversal"),
    )
    for column in ("referral_program_id", "user_id", "status", "created_at"):
        op.create_index(f"ix_referral_commissions_{column}", "referral_commissions", [column])
    op.create_table(
        "referral_payouts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("referral_program_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("provider_account_id", sa.String(length=255), nullable=True),
        sa.Column("provider_transfer_id", sa.String(length=255), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="requested"),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_by_admin_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("amount_cents > 0", name="ck_referral_payout_amount"),
        sa.CheckConstraint("currency = 'EUR'", name="ck_referral_payout_currency"),
        sa.CheckConstraint(
            "status IN ('requested', 'approved', 'processing', 'paid', 'failed', 'cancelled')",
            name="ck_referral_payout_status",
        ),
        sa.ForeignKeyConstraint(
            ["referral_program_id"], ["referral_programs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_referral_payout_idempotency"),
        sa.UniqueConstraint("provider_transfer_id"),
    )
    op.create_index(
        "ix_referral_payouts_referral_program_id", "referral_payouts", ["referral_program_id"]
    )
    op.create_index("ix_referral_payouts_status", "referral_payouts", ["status"])
    op.create_index(
        "ix_referral_payouts_created_by_admin_id", "referral_payouts", ["created_by_admin_id"]
    )
    op.create_table(
        "referral_payout_allocations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payout_id", sa.Integer(), nullable=False),
        sa.Column("commission_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("amount_cents > 0", name="ck_referral_payout_allocation_amount"),
        sa.ForeignKeyConstraint(["payout_id"], ["referral_payouts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["commission_id"], ["referral_commissions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payout_id", "commission_id", name="uq_referral_payout_allocation"),
    )
    op.create_index(
        "ix_referral_payout_allocations_payout_id", "referral_payout_allocations", ["payout_id"]
    )
    op.create_index(
        "ix_referral_payout_allocations_commission_id",
        "referral_payout_allocations",
        ["commission_id"],
    )
    op.create_table(
        "referral_owner_login_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("referral_program_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["referral_program_id"], ["referral_programs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_referral_owner_token_hash"),
    )
    op.create_index(
        "ix_referral_owner_login_tokens_referral_program_id",
        "referral_owner_login_tokens",
        ["referral_program_id"],
    )
    op.create_index(
        "ix_referral_owner_login_tokens_expires_at", "referral_owner_login_tokens", ["expires_at"]
    )
    op.create_table(
        "unsubscribed_digest_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("period_key", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="reserved"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "reserved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "period_key", name="uq_unsubscribed_digest_user_period"),
    )
    op.create_index(
        "ix_unsubscribed_digest_deliveries_user_id", "unsubscribed_digest_deliveries", ["user_id"]
    )
    op.create_index(
        "ix_unsubscribed_digest_deliveries_period_key",
        "unsubscribed_digest_deliveries",
        ["period_key"],
    )
    op.create_index(
        "ix_unsubscribed_digest_deliveries_status", "unsubscribed_digest_deliveries", ["status"]
    )


def downgrade() -> None:
    for index in (
        "ix_unsubscribed_digest_deliveries_status",
        "ix_unsubscribed_digest_deliveries_period_key",
        "ix_unsubscribed_digest_deliveries_user_id",
    ):
        op.drop_index(index, table_name="unsubscribed_digest_deliveries")
    op.drop_table("unsubscribed_digest_deliveries")
    for index in (
        "ix_referral_owner_login_tokens_expires_at",
        "ix_referral_owner_login_tokens_referral_program_id",
    ):
        op.drop_index(index, table_name="referral_owner_login_tokens")
    op.drop_table("referral_owner_login_tokens")
    for index in (
        "ix_referral_payout_allocations_commission_id",
        "ix_referral_payout_allocations_payout_id",
    ):
        op.drop_index(index, table_name="referral_payout_allocations")
    op.drop_table("referral_payout_allocations")
    for index in (
        "ix_referral_payouts_created_by_admin_id",
        "ix_referral_payouts_status",
        "ix_referral_payouts_referral_program_id",
    ):
        op.drop_index(index, table_name="referral_payouts")
    op.drop_table("referral_payouts")
    for index in (
        "ix_referral_commissions_created_at",
        "ix_referral_commissions_status",
        "ix_referral_commissions_user_id",
        "ix_referral_commissions_referral_program_id",
    ):
        op.drop_index(index, table_name="referral_commissions")
    op.drop_table("referral_commissions")
    op.drop_index("ix_user_referrals_referral_program_id", table_name="user_referrals")
    op.drop_table("user_referrals")
    for index in (
        "ix_referral_programs_created_by_admin_id",
        "ix_referral_programs_is_active",
        "ix_referral_programs_owner_telegram_user_id",
        "ix_referral_programs_owner_username_key",
        "ix_referral_programs_referral_code",
    ):
        op.drop_index(index, table_name="referral_programs")
    op.drop_table("referral_programs")
    op.drop_column("users", "digest_opted_out")
