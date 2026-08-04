from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserPlatformAccount, UserReport

MAX_REPORT_LENGTH = 4_000


class ReportValidationError(ValueError):
    pass


async def telegram_account(session: AsyncSession, user: User) -> UserPlatformAccount | None:
    return await session.scalar(
        select(UserPlatformAccount).where(
            UserPlatformAccount.platform == "telegram",
            UserPlatformAccount.platform_user_id == user.telegram_user_id,
        )
    )


async def create_report(
    session: AsyncSession, user: User, text: str, platform_account: UserPlatformAccount | None
) -> UserReport:
    value = text.strip()
    if not value:
        raise ReportValidationError("empty")
    if len(value) > MAX_REPORT_LENGTH:
        raise ReportValidationError("too-long")
    report = UserReport(
        user_id=user.id,
        platform_account_id=platform_account.id if platform_account else None,
        text=value,
    )
    session.add(report)
    await session.flush()
    return report


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
