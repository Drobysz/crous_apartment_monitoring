from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Timestamped, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger)
    telegram_username: Mapped[str | None] = mapped_column(String(32), index=True)
    language: Mapped[str] = mapped_column(String(2), default="fr")
    telegram_language_code: Mapped[str | None] = mapped_column(String(16))
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    active_navigation_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    active_navigation_message_id: Mapped[int | None]
    active_navigation_screen: Mapped[str | None] = mapped_column(String(64))
    active_navigation_version: Mapped[int] = mapped_column(Integer, default=0)
    current_fsm_state: Mapped[str | None] = mapped_column(String(64))
    trial_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Search(Timestamped, Base):
    __tablename__ = "searches"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str | None] = mapped_column(String(128))
    location_display_name: Mapped[str] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(128))
    postal_code: Mapped[str | None] = mapped_column(String(24))
    country_code: Mapped[str | None] = mapped_column(String(2))
    center_latitude: Mapped[float]
    center_longitude: Mapped[float]
    radius_km: Mapped[int | None]
    bounds_west: Mapped[float]
    bounds_north: Mapped[float]
    bounds_east: Mapped[float]
    bounds_south: Mapped[float]
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot_fingerprint: Mapped[str | None] = mapped_column(String(64))
    consecutive_errors: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    price_min_cents: Mapped[int | None]
    price_max_cents: Mapped[int | None]
    surface_min_m2: Mapped[float | None]
    surface_max_m2: Mapped[float | None]
    accommodation_format: Mapped[str | None] = mapped_column(String(16))


class SubscriptionPlan(Timestamped, Base):
    __tablename__ = "subscription_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    price_cents: Mapped[int]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Purchase(Timestamped, Base):
    __tablename__ = "purchases"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subscription_plan_id: Mapped[int] = mapped_column(ForeignKey("subscription_plans.id"), index=True)
    stripe_checkout_session_id: Mapped[str] = mapped_column(String(255), unique=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), index=True)
    stripe_event_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    amount_cents: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(32), index=True)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSubscription(Timestamped, Base):
    __tablename__ = "user_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subscription_plan_id: Mapped[int] = mapped_column(ForeignKey("subscription_plans.id"), index=True)
    purchase_id: Mapped[int | None] = mapped_column(ForeignKey("purchases.id", ondelete="SET NULL"), unique=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    activation_source: Mapped[str] = mapped_column(String(16))
    expiration_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SearchDisplayGroup(Base):
    """One complete Telegram rendering of a search snapshot.

    A group is made active only after every message has been sent and recorded.
    This leaves a previously active list recoverable when Telegram delivery fails.
    """

    __tablename__ = "search_display_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    search_id: Mapped[int] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), index=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    listing_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SearchDisplayMessage(Base):
    __tablename__ = "search_display_messages"
    __table_args__ = (UniqueConstraint("display_group_id", "telegram_message_id", name="uq_display_message"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    display_group_id: Mapped[int] = mapped_column(ForeignKey("search_display_groups.id", ondelete="CASCADE"), index=True)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger)
    message_kind: Mapped[str] = mapped_column(String(16), default="card")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Listing(Timestamped, Base):
    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_listing_source_external"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(24), default="crous")
    external_id: Mapped[str] = mapped_column(String(128))
    canonical_url: Mapped[str] = mapped_column(String(1024), unique=True)
    title: Mapped[str] = mapped_column(String(512))
    residence_name: Mapped[str | None] = mapped_column(String(512))
    accommodation_type: Mapped[str | None] = mapped_column(String(255))
    occupancy_type: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(255))
    postal_code: Mapped[str | None] = mapped_column(String(24))
    address: Mapped[str | None] = mapped_column(String(1024))
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]
    price_original: Mapped[str | None] = mapped_column(String(64))
    price_cents: Mapped[int | None]
    surface_original: Mapped[str | None] = mapped_column(String(64))
    surface_min: Mapped[float | None]
    surface_max: Mapped[float | None]
    bed_information: Mapped[str | None] = mapped_column(String(255))
    sanitary_information: Mapped[str | None] = mapped_column(String(512))
    kitchen_information: Mapped[str | None] = mapped_column(String(512))
    equipment: Mapped[str | None] = mapped_column(Text)
    availability_text: Mapped[str | None] = mapped_column(String(255))
    short_description: Mapped[str | None] = mapped_column(Text)
    primary_image_url: Mapped[str | None] = mapped_column(String(1024))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SearchListing(Base):
    __tablename__ = "search_listings"
    search_id: Mapped[int] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    disappeared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reappeared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_currently_available: Mapped[bool] = mapped_column(Boolean, default=True)
    notification_count: Mapped[int] = mapped_column(default=0)
    last_notification_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImageCache(Base):
    __tablename__ = "image_cache"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_url: Mapped[str] = mapped_column(String(1024), unique=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String(512))
    content_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    mime_type: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None]
    width: Mapped[int | None]
    height: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    search_id: Mapped[int] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"))
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    notification_type: Mapped[str] = mapped_column(String(32))
    telegram_message_id: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class HousingDailyStatistic(Base):
    __tablename__ = "housing_daily_statistics"
    __table_args__ = (UniqueConstraint("search_id", "statistic_date", name="uq_housing_daily_stat_search_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    search_id: Mapped[int] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), index=True)
    search_identifier: Mapped[str] = mapped_column(String(128))
    cheapest_price_cents: Mapped[int | None]
    highest_price_cents: Mapped[int | None]
    unique_apartment_count: Mapped[int] = mapped_column(Integer)
    statistic_date: Mapped[date] = mapped_column(Date, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FavoriteRestaurant(Timestamped, Base):
    __tablename__ = "favorite_restaurants"
    __table_args__ = (UniqueConstraint("user_id", "restaurant_code", name="uq_favorite_restaurant_user_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    restaurant_code: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(255))
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RestaurantSubscription(Timestamped, Base):
    __tablename__ = "restaurant_subscriptions"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    primary_restaurant_id: Mapped[int | None] = mapped_column(ForeignKey("favorite_restaurants.id", ondelete="SET NULL"), unique=True, index=True)
    delivery_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_time: Mapped[time] = mapped_column(Time, default=lambda: time(hour=8))


class RestaurantMenuDelivery(Base):
    __tablename__ = "restaurant_menu_deliveries"
    __table_args__ = (UniqueConstraint("user_id", "delivery_date", name="uq_restaurant_delivery_user_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    favorite_restaurant_id: Mapped[int | None] = mapped_column(ForeignKey("favorite_restaurants.id", ondelete="SET NULL"), index=True)
    delivery_date: Mapped[date] = mapped_column(Date, index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    telegram_message_id: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GeocodingCache(Base):
    __tablename__ = "geocoding_cache"
    query: Mapped[str] = mapped_column(String(512), primary_key=True)
    locale: Mapped[str] = mapped_column(String(8), primary_key=True)
    response: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Admin(Timestamped, Base):
    __tablename__ = "admins"
    __table_args__ = (CheckConstraint("role IN ('admin', 'superadmin')", name="ck_admins_role"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    username: Mapped[str] = mapped_column(String(33))
    username_key: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="admin", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminAudit(Base):
    __tablename__ = "admin_audits"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_admin_id: Mapped[int | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdminNotificationChat(Timestamped, Base):
    """A private notification-bot chat verified against an active admin username."""

    __tablename__ = "admin_notification_chats"
    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"), unique=True, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
