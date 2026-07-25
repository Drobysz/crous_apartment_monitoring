from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
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
    language: Mapped[str] = mapped_column(String(2), default="fr")
    telegram_language_code: Mapped[str | None] = mapped_column(String(16))
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    active_navigation_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    active_navigation_message_id: Mapped[int | None]
    active_navigation_screen: Mapped[str | None] = mapped_column(String(64))
    active_navigation_version: Mapped[int] = mapped_column(Integer, default=0)
    current_fsm_state: Mapped[str | None] = mapped_column(String(64))


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
    check_interval_minutes: Mapped[int] = mapped_column(default=120)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_errors: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_initialized: Mapped[bool] = mapped_column(Boolean, default=False)


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


class GeocodingCache(Base):
    __tablename__ = "geocoding_cache"
    query: Mapped[str] = mapped_column(String(512), primary_key=True)
    locale: Mapped[str] = mapped_column(String(8), primary_key=True)
    response: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
