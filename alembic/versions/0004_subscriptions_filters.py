"""Add subscriptions, purchases and search filters.

Revision ID: 0004_subscriptions_filters
Revises: 0003_snapshot_display_groups
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_subscriptions_filters"
down_revision = "0003_snapshot_display_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("trial_used_at", sa.DateTime(timezone=True)))
    op.add_column("searches", sa.Column("price_min_cents", sa.Integer()))
    op.add_column("searches", sa.Column("price_max_cents", sa.Integer()))
    op.add_column("searches", sa.Column("surface_min_m2", sa.Float()))
    op.add_column("searches", sa.Column("surface_max_m2", sa.Float()))
    op.add_column("searches", sa.Column("accommodation_format", sa.String(length=16)))
    op.create_table("subscription_plans",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False), sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code"))
    op.create_index("ix_subscription_plans_code", "subscription_plans", ["code"])
    op.create_index("ix_subscription_plans_is_active", "subscription_plans", ["is_active"])
    plans = sa.table("subscription_plans", sa.column("code", sa.String), sa.column("name", sa.String), sa.column("price_cents", sa.Integer), sa.column("is_active", sa.Boolean))
    op.bulk_insert(plans, [
        {"code": "season", "name": "Season", "price_cents": 1000, "is_active": True},
        {"code": "lifetime", "name": "Lifetime", "price_cents": 2400, "is_active": True},
    ])
    op.create_table("purchases",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_plan_id", sa.Integer(), sa.ForeignKey("subscription_plans.id"), nullable=False), sa.Column("stripe_checkout_session_id", sa.String(length=255), nullable=False),
        sa.Column("stripe_payment_intent_id", sa.String(length=255)), sa.Column("stripe_event_id", sa.String(length=255)), sa.Column("amount_cents", sa.Integer()),
        sa.Column("status", sa.String(length=32), nullable=False), sa.Column("purchased_at", sa.DateTime(timezone=True)), sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("stripe_checkout_session_id"), sa.UniqueConstraint("stripe_event_id"))
    op.create_index("ix_purchases_user_id", "purchases", ["user_id"]); op.create_index("ix_purchases_subscription_plan_id", "purchases", ["subscription_plan_id"])
    op.create_index("ix_purchases_stripe_payment_intent_id", "purchases", ["stripe_payment_intent_id"]); op.create_index("ix_purchases_status", "purchases", ["status"])
    op.create_table("user_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_plan_id", sa.Integer(), sa.ForeignKey("subscription_plans.id"), nullable=False), sa.Column("purchase_id", sa.Integer(), sa.ForeignKey("purchases.id", ondelete="SET NULL")),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False), sa.Column("ends_at", sa.DateTime(timezone=True)), sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("activation_source", sa.String(length=16), nullable=False), sa.Column("expiration_notified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("purchase_id"))
    op.create_index("ix_user_subscriptions_user_id", "user_subscriptions", ["user_id"]); op.create_index("ix_user_subscriptions_subscription_plan_id", "user_subscriptions", ["subscription_plan_id"])
    op.create_index("ix_user_subscriptions_starts_at", "user_subscriptions", ["starts_at"]); op.create_index("ix_user_subscriptions_ends_at", "user_subscriptions", ["ends_at"]); op.create_index("ix_user_subscriptions_status", "user_subscriptions", ["status"])


def downgrade() -> None:
    for index, table in (("ix_user_subscriptions_status", "user_subscriptions"), ("ix_user_subscriptions_ends_at", "user_subscriptions"), ("ix_user_subscriptions_starts_at", "user_subscriptions"), ("ix_user_subscriptions_subscription_plan_id", "user_subscriptions"), ("ix_user_subscriptions_user_id", "user_subscriptions")):
        op.drop_index(index, table_name=table)
    op.drop_table("user_subscriptions")
    for index in ("ix_purchases_status", "ix_purchases_stripe_payment_intent_id", "ix_purchases_subscription_plan_id", "ix_purchases_user_id"):
        op.drop_index(index, table_name="purchases")
    op.drop_table("purchases")
    op.drop_index("ix_subscription_plans_is_active", table_name="subscription_plans"); op.drop_index("ix_subscription_plans_code", table_name="subscription_plans"); op.drop_table("subscription_plans")
    for column in ("accommodation_format", "surface_max_m2", "surface_min_m2", "price_max_cents", "price_min_cents"): op.drop_column("searches", column)
    op.drop_column("users", "trial_used_at")
