from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    FavoriteAvailabilityState,
    FavoriteTransitionEvent,
    HousingFavorite,
    Listing,
    Search,
    User,
)
from app.notifications.gateway import NotificationGateway


async def add_favorite(session: AsyncSession, user: User, listing_id: int) -> bool:
    """Save a canonical listing once; an already-saved listing is a success."""
    if await session.get(Listing, listing_id) is None:
        return False
    exists = await session.scalar(
        select(HousingFavorite.id).where(
            HousingFavorite.user_id == user.id, HousingFavorite.listing_id == listing_id
        )
    )
    if exists is not None:
        return True
    try:
        async with session.begin_nested():
            session.add(HousingFavorite(user_id=user.id, listing_id=listing_id))
            await session.flush()
    except IntegrityError:
        # The database unique constraint is the concurrency guarantee.
        return True
    return True


async def remove_favorite(session: AsyncSession, user: User, listing_id: int) -> bool:
    """Ownership-scoped and idempotent removal."""
    await session.execute(
        delete(HousingFavorite).where(
            HousingFavorite.user_id == user.id, HousingFavorite.listing_id == listing_id
        )
    )
    return True


async def favorites(session: AsyncSession, user: User) -> list[Listing]:
    return list(
        (
            await session.scalars(
                select(Listing)
                .join(HousingFavorite, HousingFavorite.listing_id == Listing.id)
                .where(HousingFavorite.user_id == user.id)
                .order_by(HousingFavorite.created_at.desc(), HousingFavorite.id.desc())
            )
        ).all()
    )


async def favorite_listing_ids(session: AsyncSession, user_id: int) -> set[int]:
    return set(
        (
            await session.scalars(
                select(HousingFavorite.listing_id).where(HousingFavorite.user_id == user_id)
            )
        ).all()
    )


async def record_completed_snapshot_transitions(
    session: AsyncSession, search: Search, current_listing_ids: set[int]
) -> list[FavoriteTransitionEvent]:
    """Record only completed-result transitions for the search owner.

    The first observation establishes a baseline. This function must never be
    called for a failed or partial upstream response. Search-level locking is
    performed by the caller; the unique outbox identity also protects retries.
    """
    now = datetime.now(UTC)
    values = list(
        (
            await session.scalars(
                select(HousingFavorite).where(HousingFavorite.user_id == search.user_id)
            )
        ).all()
    )
    events: list[FavoriteTransitionEvent] = []
    for favorite in values:
        available = favorite.listing_id in current_listing_ids
        state = await session.scalar(
            select(FavoriteAvailabilityState)
            .where(
                FavoriteAvailabilityState.favorite_id == favorite.id,
                FavoriteAvailabilityState.search_id == search.id,
            )
            .with_for_update()
        )
        if state is None:
            session.add(
                FavoriteAvailabilityState(
                    favorite_id=favorite.id,
                    search_id=search.id,
                    is_available=available,
                    observed_at=now,
                )
            )
            continue
        if state.is_available == available:
            state.observed_at = now
            continue
        state.is_available = available
        state.observed_at = now
        state.transition_sequence += 1
        event = FavoriteTransitionEvent(
            availability_state_id=state.id,
            user_id=search.user_id,
            listing_id=favorite.listing_id,
            transition="appeared" if available else "disappeared",
            transition_sequence=state.transition_sequence,
        )
        session.add(event)
        events.append(event)
    await session.flush()
    return events


async def dispatch_pending_transitions(session: AsyncSession, gateway: NotificationGateway) -> int:
    """Deliver committed outbox rows and retain failures for a later retry."""
    rows = list(
        (
            await session.execute(
                select(FavoriteTransitionEvent, User, Listing)
                .join(User, User.id == FavoriteTransitionEvent.user_id)
                .join(Listing, Listing.id == FavoriteTransitionEvent.listing_id)
                .where(FavoriteTransitionEvent.status == "pending")
                .order_by(FavoriteTransitionEvent.id)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    delivered = 0
    for event, user, listing in rows:
        try:
            await gateway.send_favourite_transition(
                recipient_id=user.telegram_chat_id,
                language=user.language,
                title=listing.title,
                transition=event.transition,
            )
        except Exception as error:
            event.error = str(error)[:2000]
        else:
            event.status = "sent"
            event.sent_at = datetime.now(UTC)
            event.error = None
            delivered += 1
    return delivered
