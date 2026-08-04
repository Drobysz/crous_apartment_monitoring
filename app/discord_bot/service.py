from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import detect_language
from app.db.models import User, UserPlatformAccount


async def get_or_create_discord_user(
    session: AsyncSession,
    discord_user_id: int,
    channel_id: int,
    username: str | None,
    locale: str | None,
) -> User:
    account = await session.scalar(
        select(UserPlatformAccount).where(
            UserPlatformAccount.platform == "discord",
            UserPlatformAccount.platform_user_id == discord_user_id,
        )
    )
    if account is not None:
        account.platform_chat_id = channel_id
        account.platform_username = username
        user = await session.get(User, account.user_id)
        if user is None:
            raise RuntimeError("platform account has no user")
        return user
    user = User(language=detect_language(locale), telegram_language_code=locale)
    session.add(user)
    await session.flush()
    session.add(
        UserPlatformAccount(
            user_id=user.id,
            platform="discord",
            platform_user_id=discord_user_id,
            platform_chat_id=channel_id,
            platform_username=username,
        )
    )
    return user
