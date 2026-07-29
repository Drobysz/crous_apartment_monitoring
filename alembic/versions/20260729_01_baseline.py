"""Create the complete CROUS monitoring schema.

Revision ID: 20260729_01_baseline
Revises:
Create Date: 2026-07-29
"""

import sqlalchemy as sa

from alembic import op

revision = "20260729_01_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column("telegram_language_code", sa.String(length=16), nullable=True),
        sa.Column("is_blocked", sa.Boolean(), nullable=False),
        sa.Column("active_navigation_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("active_navigation_message_id", sa.Integer(), nullable=True),
        sa.Column("active_navigation_screen", sa.String(length=64), nullable=True),
        sa.Column("active_navigation_version", sa.Integer(), nullable=False),
        sa.Column("current_fsm_state", sa.String(length=64), nullable=True),
        sa.Column("trial_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("ix_users_telegram_user_id", "users", ["telegram_user_id"], unique=True)

    op.create_table(
        "searches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("location_display_name", sa.String(length=255), nullable=False),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("postal_code", sa.String(length=24), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("center_latitude", sa.Float(), nullable=False),
        sa.Column("center_longitude", sa.Float(), nullable=False),
        sa.Column("radius_km", sa.Integer(), nullable=True),
        sa.Column("bounds_west", sa.Float(), nullable=False),
        sa.Column("bounds_north", sa.Float(), nullable=False),
        sa.Column("bounds_east", sa.Float(), nullable=False),
        sa.Column("bounds_south", sa.Float(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("consecutive_errors", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("price_min_cents", sa.Integer(), nullable=True),
        sa.Column("price_max_cents", sa.Integer(), nullable=True),
        sa.Column("surface_min_m2", sa.Float(), nullable=True),
        sa.Column("surface_max_m2", sa.Float(), nullable=True),
        sa.Column("accommodation_format", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_searches_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_searches"),
    )
    op.create_index("ix_searches_user_id", "searches", ["user_id"])

    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_subscription_plans"),
    )
    op.create_index("ix_subscription_plans_code", "subscription_plans", ["code"], unique=True)
    op.create_index("ix_subscription_plans_is_active", "subscription_plans", ["is_active"])
    subscription_plans = sa.table(
        "subscription_plans",
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("price_cents", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        subscription_plans,
        [
            {"code": "season", "name": "Season", "price_cents": 1000, "is_active": True},
            {"code": "lifetime", "name": "Lifetime", "price_cents": 2400, "is_active": True},
        ],
    )

    op.create_table(
        "purchases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("subscription_plan_id", sa.Integer(), nullable=False),
        sa.Column("stripe_checkout_session_id", sa.String(length=255), nullable=False),
        sa.Column("stripe_payment_intent_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_event_id", sa.String(length=255), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["subscription_plan_id"], ["subscription_plans.id"], name="fk_purchases_plan_id_subscription_plans"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_purchases_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_purchases"),
        sa.UniqueConstraint("stripe_checkout_session_id", name="uq_purchases_stripe_checkout_session_id"),
        sa.UniqueConstraint("stripe_event_id", name="uq_purchases_stripe_event_id"),
    )
    op.create_index("ix_purchases_user_id", "purchases", ["user_id"])
    op.create_index("ix_purchases_subscription_plan_id", "purchases", ["subscription_plan_id"])
    op.create_index("ix_purchases_stripe_payment_intent_id", "purchases", ["stripe_payment_intent_id"])
    op.create_index("ix_purchases_status", "purchases", ["status"])

    op.create_table(
        "user_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("subscription_plan_id", sa.Integer(), nullable=False),
        sa.Column("purchase_id", sa.Integer(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("activation_source", sa.String(length=16), nullable=False),
        sa.Column("expiration_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["purchase_id"], ["purchases.id"], name="fk_user_subscriptions_purchase_id_purchases", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["subscription_plan_id"], ["subscription_plans.id"], name="fk_user_subscriptions_plan_id_subscription_plans"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_subscriptions_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_user_subscriptions"),
        sa.UniqueConstraint("purchase_id", name="uq_user_subscriptions_purchase_id"),
    )
    op.create_index("ix_user_subscriptions_user_id", "user_subscriptions", ["user_id"])
    op.create_index("ix_user_subscriptions_subscription_plan_id", "user_subscriptions", ["subscription_plan_id"])
    op.create_index("ix_user_subscriptions_starts_at", "user_subscriptions", ["starts_at"])
    op.create_index("ix_user_subscriptions_ends_at", "user_subscriptions", ["ends_at"])
    op.create_index("ix_user_subscriptions_status", "user_subscriptions", ["status"])

    op.create_table(
        "search_display_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("search_id", sa.Integer(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("listing_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["search_id"], ["searches.id"], name="fk_search_display_groups_search_id_searches", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_search_display_groups"),
    )
    op.create_index("ix_search_display_groups_search_id", "search_display_groups", ["search_id"])
    op.create_index("ix_search_display_groups_fingerprint", "search_display_groups", ["fingerprint"])
    op.create_index("ix_search_display_groups_status", "search_display_groups", ["status"])

    op.create_table(
        "search_display_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("display_group_id", sa.Integer(), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("message_kind", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["display_group_id"], ["search_display_groups.id"], name="fk_search_display_messages_group_id_groups", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_search_display_messages"),
        sa.UniqueConstraint("display_group_id", "telegram_message_id", name="uq_display_message"),
    )
    op.create_index("ix_search_display_messages_display_group_id", "search_display_messages", ["display_group_id"])

    op.create_table(
        "listings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("canonical_url", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("residence_name", sa.String(length=512), nullable=True),
        sa.Column("accommodation_type", sa.String(length=255), nullable=True),
        sa.Column("occupancy_type", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=255), nullable=True),
        sa.Column("postal_code", sa.String(length=24), nullable=True),
        sa.Column("address", sa.String(length=1024), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("price_original", sa.String(length=64), nullable=True),
        sa.Column("price_cents", sa.Integer(), nullable=True),
        sa.Column("surface_original", sa.String(length=64), nullable=True),
        sa.Column("surface_min", sa.Float(), nullable=True),
        sa.Column("surface_max", sa.Float(), nullable=True),
        sa.Column("bed_information", sa.String(length=255), nullable=True),
        sa.Column("sanitary_information", sa.String(length=512), nullable=True),
        sa.Column("kitchen_information", sa.String(length=512), nullable=True),
        sa.Column("equipment", sa.Text(), nullable=True),
        sa.Column("availability_text", sa.String(length=255), nullable=True),
        sa.Column("short_description", sa.Text(), nullable=True),
        sa.Column("primary_image_url", sa.String(length=1024), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_listings"),
        sa.UniqueConstraint("canonical_url", name="uq_listings_canonical_url"),
        sa.UniqueConstraint("source", "external_id", name="uq_listing_source_external"),
    )

    op.create_table(
        "search_listings",
        sa.Column("search_id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("disappeared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reappeared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_currently_available", sa.Boolean(), nullable=False),
        sa.Column("notification_count", sa.Integer(), nullable=False),
        sa.Column("last_notification_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], name="fk_search_listings_listing_id_listings", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["search_id"], ["searches.id"], name="fk_search_listings_search_id_searches", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("search_id", "listing_id", name="pk_search_listings"),
    )

    op.create_table(
        "image_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=False),
        sa.Column("telegram_file_id", sa.String(length=512), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("mime_type", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_image_cache"),
        sa.UniqueConstraint("source_url", name="uq_image_cache_source_url"),
    )
    op.create_index("ix_image_cache_content_hash", "image_cache", ["content_hash"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("search_id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("notification_type", sa.String(length=32), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], name="fk_notifications_listing_id_listings", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["search_id"], ["searches.id"], name="fk_notifications_search_id_searches", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_notifications_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
    )

    op.create_table(
        "geocoding_cache",
        sa.Column("query", sa.String(length=512), nullable=False),
        sa.Column("locale", sa.String(length=8), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("query", "locale", name="pk_geocoding_cache"),
    )


def downgrade() -> None:
    op.drop_table("geocoding_cache")
    op.drop_table("notifications")
    op.drop_index("ix_image_cache_content_hash", table_name="image_cache")
    op.drop_table("image_cache")
    op.drop_table("search_listings")
    op.drop_table("listings")
    op.drop_index("ix_search_display_messages_display_group_id", table_name="search_display_messages")
    op.drop_table("search_display_messages")
    op.drop_index("ix_search_display_groups_status", table_name="search_display_groups")
    op.drop_index("ix_search_display_groups_fingerprint", table_name="search_display_groups")
    op.drop_index("ix_search_display_groups_search_id", table_name="search_display_groups")
    op.drop_table("search_display_groups")
    op.drop_index("ix_user_subscriptions_status", table_name="user_subscriptions")
    op.drop_index("ix_user_subscriptions_ends_at", table_name="user_subscriptions")
    op.drop_index("ix_user_subscriptions_starts_at", table_name="user_subscriptions")
    op.drop_index("ix_user_subscriptions_subscription_plan_id", table_name="user_subscriptions")
    op.drop_index("ix_user_subscriptions_user_id", table_name="user_subscriptions")
    op.drop_table("user_subscriptions")
    op.drop_index("ix_purchases_status", table_name="purchases")
    op.drop_index("ix_purchases_stripe_payment_intent_id", table_name="purchases")
    op.drop_index("ix_purchases_subscription_plan_id", table_name="purchases")
    op.drop_index("ix_purchases_user_id", table_name="purchases")
    op.drop_table("purchases")
    op.drop_index("ix_subscription_plans_is_active", table_name="subscription_plans")
    op.drop_index("ix_subscription_plans_code", table_name="subscription_plans")
    op.drop_table("subscription_plans")
    op.drop_index("ix_searches_user_id", table_name="searches")
    op.drop_table("searches")
    op.drop_index("ix_users_telegram_user_id", table_name="users")
    op.drop_table("users")
