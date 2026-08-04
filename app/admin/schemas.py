from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class AdminCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=12, max_length=72)
    role: Literal["admin", "superadmin"] = "admin"


class AdminUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    password: str | None = Field(default=None, min_length=12, max_length=72)
    role: Literal["admin", "superadmin"] | None = None
    is_active: bool | None = None


class AdminResponse(BaseModel):
    id: int
    name: str
    username: str
    role: Literal["admin", "superadmin"]
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class AdminProfileResponse(AdminResponse):
    pass


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int


class AdminPageResponse(BaseModel):
    items: list[AdminResponse]
    meta: PageMeta


class RevenuePoint(BaseModel):
    key: str
    amount_cents: int


class DashboardResponse(BaseModel):
    total_users: int
    active_paid_subscribers: int
    active_monitoring_anchors: int
    revenue_cents: int
    revenue_series: list[RevenuePoint]


class BuyerResponse(BaseModel):
    purchase_id: int
    username: str | None
    plan: str
    amount_cents: int
    purchased_at: datetime | None
    status: str


class PaidUserResponse(BaseModel):
    user_id: int
    username: str | None
    current_plan: str
    starts_at: datetime
    ends_at: datetime | None
    status: str
    last_payment_at: datetime | None
    active_monitoring_count: int


class PaidUserPageResponse(BaseModel):
    items: list[PaidUserResponse]
    meta: PageMeta


class UserDetailsResponse(PaidUserResponse):
    language: str
    searches: list[dict[str, object]]


class TransactionResponse(BaseModel):
    id: int
    username: str | None
    plan: str
    amount_cents: int | None
    status: str
    is_test: bool
    stripe_checkout_session_id: str
    stripe_payment_intent_id: str | None
    purchased_at: datetime | None
    created_at: datetime


class TransactionPageResponse(BaseModel):
    items: list[TransactionResponse]
    meta: PageMeta


class TransactionDetailsResponse(TransactionResponse):
    processed_at: datetime | None
    user_id: int


class ReportResponse(BaseModel):
    id: int
    user_id: int
    username: str | None
    preview: str
    created_at: datetime


class ReportPageResponse(BaseModel):
    items: list[ReportResponse]
    meta: PageMeta


class ReportDetailsResponse(ReportResponse):
    text: str
    platform: str | None
    platform_user_id: int | None


class ReferralCreateRequest(BaseModel):
    owner_telegram_username: str = Field(min_length=1, max_length=33)
    referral_code: str = Field(min_length=3, max_length=64)


class ReferralUpdateRequest(BaseModel):
    is_active: bool


class ReferralPayoutRequest(BaseModel):
    amount_cents: int = Field(ge=500)
    idempotency_key: str = Field(min_length=16, max_length=128)


class ReferralPayoutActionRequest(BaseModel):
    external_reference: str | None = Field(default=None, max_length=255)
    failure_code: str | None = Field(default=None, max_length=64)


class ReferralOwnerExchangeRequest(BaseModel):
    token: str = Field(min_length=20, max_length=255)
