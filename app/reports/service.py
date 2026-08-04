from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserPlatformAccount, UserReport

MAX_REPORT_LENGTH = 4_000
REPORT_COOLDOWN = timedelta(hours=1)


class ReportValidationError(ValueError):
    pass


class ReportCooldownError(ReportValidationError):
    def __init__(self, remaining_seconds: int) -> None:
        super().__init__("report_cooldown_active")
        self.remaining_seconds = remaining_seconds


async def telegram_account(session: AsyncSession, user: User) -> UserPlatformAccount | None:
    return await session.scalar(
        select(UserPlatformAccount).where(
            UserPlatformAccount.platform == "telegram",
            UserPlatformAccount.platform_user_id == user.telegram_user_id,
        )
    )


async def create_report(
    session: AsyncSession,
    user: User,
    text: str,
    platform_account: UserPlatformAccount | None,
    *,
    now: datetime | None = None,
) -> UserReport:
    value = text.strip()
    if not value:
        raise ReportValidationError("empty")
    if len(value) > MAX_REPORT_LENGTH:
        raise ReportValidationError("too-long")
    # Serialising creations by user makes the read/check/write sequence safe
    # on PostgreSQL. A failed surrounding transaction leaves no cooldown row.
    await session.scalar(select(User.id).where(User.id == user.id).with_for_update())
    now = now or datetime.now(UTC)
    latest = await session.scalar(
        select(UserReport)
        .where(UserReport.user_id == user.id)
        .order_by(UserReport.created_at.desc(), UserReport.id.desc())
        .limit(1)
    )
    if latest is not None:
        created_at = latest.created_at
        created_at = (
            created_at.replace(tzinfo=UTC)
            if created_at.tzinfo is None
            else created_at.astimezone(UTC)
        )
        remaining = REPORT_COOLDOWN - (now - created_at)
        if remaining.total_seconds() > 0:
            raise ReportCooldownError(max(1, int(remaining.total_seconds())))
    report = UserReport(
        user_id=user.id,
        platform_account_id=platform_account.id if platform_account else None,
        text=value,
        created_at=now,
    )
    session.add(report)
    await session.flush()
    return report


async def report_cooldown_remaining(
    session: AsyncSession, user: User, *, now: datetime | None = None
) -> int:
    """A non-locking preflight for adapters; persistence repeats the check under lock."""
    now = now or datetime.now(UTC)
    latest = await session.scalar(
        select(UserReport.created_at)
        .where(UserReport.user_id == user.id)
        .order_by(UserReport.created_at.desc(), UserReport.id.desc())
        .limit(1)
    )
    if latest is None:
        return 0
    created_at = latest.replace(tzinfo=UTC) if latest.tzinfo is None else latest.astimezone(UTC)
    return max(0, int((REPORT_COOLDOWN - (now - created_at)).total_seconds()))


async def user_reports(
    session: AsyncSession, user: User, *, limit: int = 20, offset: int = 0
) -> list[UserReport]:
    return list(
        (
            await session.scalars(
                select(UserReport)
                .where(UserReport.user_id == user.id)
                .order_by(UserReport.created_at.desc(), UserReport.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
