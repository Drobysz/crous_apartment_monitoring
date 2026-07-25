from __future__ import annotations

from datetime import datetime
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.i18n import Translator, i18n
from app.crous.models import CrousListing


def card_caption(listing: CrousListing, language: str, first_seen_at: datetime, available_again: bool = False, translator: Translator = i18n) -> str:
    lines = [f"<b>🏠 {escape(listing.title)}</b>"]
    if available_again: lines += ["", f"<b>{translator.text(language, 'available-again')}</b>"]
    fields = [("price", listing.price_original), ("surface", listing.surface_original), ("address", listing.address), ("occupancy", listing.occupancy_type), ("beds", listing.bed_information), ("sanitary", listing.sanitary_information), ("kitchen", listing.kitchen_information)]
    for key, value in fields:
        if value: lines.append(translator.text(language, key, value=escape(value)))
    lines += [translator.text(language, "first-detected", value=first_seen_at.strftime("%d/%m/%Y %H:%M")), translator.text(language, "source")]
    return "\n".join(lines)[:1024]


def card_keyboard(listing: CrousListing, language: str, translator: Translator = i18n) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=translator.text(language, "open-crous"), url=listing.canonical_url)]])
