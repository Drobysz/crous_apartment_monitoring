from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callbacks import NavCallback
from app.core.i18n import Translator, i18n


def main_menu(language: str, version: int, translator: Translator = i18n) -> InlineKeyboardMarkup:
    def button(key: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=translator.text(language, key), callback_data=NavCallback(action=action, version=version).pack())
    return InlineKeyboardMarkup(inline_keyboard=[[button("set-location", "location")], [button("view-available", "list")], [button("set-interval", "interval")], [button("language", "language")]])


def back(language: str, version: int, action: str = "menu", translator: Translator = i18n) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=translator.text(language, "back"), callback_data=NavCallback(action=action, version=version).pack())]])


def location_menu(language: str, version: int, translator: Translator = i18n) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=translator.text(language, "search-city"), callback_data=NavCallback(action="city", version=version).pack())],
        [InlineKeyboardButton(text=translator.text(language, "use-location"), callback_data=NavCallback(action="geo", version=version).pack())],
        [InlineKeyboardButton(text=translator.text(language, "back"), callback_data=NavCallback(action="menu", version=version).pack())],
    ])


def language_menu(language: str, version: int, translator: Translator = i18n) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=NavCallback(action="lang", entity=index, version=version).pack())] for index, label in enumerate(("🇷🇺 Русский", "🇫🇷 Français", "🇸🇦 العربية"))]
    rows.append([InlineKeyboardButton(text=translator.text(language, "back"), callback_data=NavCallback(action="menu", version=version).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def interval_menu(language: str, version: int, translator: Translator = i18n) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{hours} h", callback_data=NavCallback(action="interval-set", entity=hours, version=version).pack())] for hours in (1, 2, 3, 6, 12, 24)]
    rows.append([InlineKeyboardButton(text=translator.text(language, "back"), callback_data=NavCallback(action="menu", version=version).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def radius_menu(language: str, version: int, translator: Translator = i18n) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{radius} km", callback_data=NavCallback(action="radius", entity=radius, version=version).pack())] for radius in (3, 5, 10, 20)]
    rows.append([InlineKeyboardButton(text=translator.text(language, "entire-city"), callback_data=NavCallback(action="radius", entity=0, version=version).pack())])
    rows.append([InlineKeyboardButton(text=translator.text(language, "back"), callback_data=NavCallback(action="location", version=version).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)
