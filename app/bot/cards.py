from __future__ import annotations

from datetime import datetime

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile

from app.crous.models import CrousListing
from app.images.downloader import SafeImageDownloader
from app.notifications.renderer import card_caption, card_keyboard


async def send_accommodation_card(
    bot: Bot,
    chat_id: int,
    listing: CrousListing,
    language: str,
    first_seen_at: datetime,
    *,
    available_again: bool = False,
    downloader: SafeImageDownloader | None = None,
    listing_id: int | None = None,
    is_favorite: bool = False,
    favourites_view: bool = False,
) -> int:
    caption = card_caption(listing, language, first_seen_at, available_again)
    keyboard = card_keyboard(
        listing,
        language,
        listing_id=listing_id,
        is_favorite=is_favorite,
        favourites_view=favourites_view,
    )
    if listing.primary_image_url:
        try:
            message = await bot.send_photo(
                chat_id,
                listing.primary_image_url,
                caption=caption,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
            return message.message_id
        except Exception:
            if downloader:
                try:
                    image = await downloader.download(listing.primary_image_url)
                    message = await bot.send_photo(
                        chat_id,
                        BufferedInputFile(image.content, "crous-image"),
                        caption=caption,
                        reply_markup=keyboard,
                        parse_mode=ParseMode.HTML,
                    )
                    return message.message_id
                except Exception:
                    pass
    message = await bot.send_message(
        chat_id, caption, reply_markup=keyboard, parse_mode=ParseMode.HTML
    )
    return message.message_id
