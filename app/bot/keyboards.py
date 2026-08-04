from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callbacks import NavCallback
from app.core.i18n import Translator, i18n


def main_menu(
    language: str,
    version: int,
    translator: Translator = i18n,
    *,
    show_test_reset: bool = False,
    monitoring_enabled: bool = False,
) -> InlineKeyboardMarkup:
    def button(key: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=translator.text(language, key),
            callback_data=NavCallback(action=action, version=version).pack(),
        )

    rows = [
        [button("housing-monitoring", "housing"), button("restaurant", "restaurant")],
        [button("reports", "reports"), button("subscription", "subscription")],
        [button("language", "language")],
    ]
    if show_test_reset:
        rows.append([button("test-reset-subscription", "test-reset")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def housing_menu(
    language: str, version: int, *, monitoring_enabled: bool, translator: Translator = i18n
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=translator.text(language, "view-available"),
                callback_data=NavCallback(action="list", version=version).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text=translator.text(language, "housing-favorites"),
                callback_data=NavCallback(action="housing-favorites", version=version).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text=translator.text(language, "filters"),
                callback_data=NavCallback(action="filters", version=version).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text=translator.text(language, "check-now"),
                callback_data=NavCallback(action="check-now", version=version).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text=translator.text(
                    language, "disable-monitoring" if monitoring_enabled else "enable-monitoring"
                ),
                callback_data=NavCallback(action="monitor-toggle", version=version).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text=translator.text(language, "set-location"),
                callback_data=NavCallback(action="location", version=version).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text=translator.text(language, "back"),
                callback_data=NavCallback(action="menu", version=version).pack(),
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def restaurant_menu(
    language: str, version: int, translator: Translator = i18n
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=translator.text(language, "restaurant-select"),
                callback_data=NavCallback(action="restaurant-select", version=version).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text=translator.text(language, "restaurant-info"),
                callback_data=NavCallback(action="restaurant-info", version=version).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text=translator.text(language, "restaurant-menu"),
                callback_data=NavCallback(action="restaurant-menu", version=version).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text=translator.text(language, "restaurant-delivery"),
                callback_data=NavCallback(action="restaurant-delivery", version=version).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text=translator.text(language, "back"),
                callback_data=NavCallback(action="menu", version=version).pack(),
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back(
    language: str, version: int, action: str = "menu", translator: Translator = i18n
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=translator.text(language, "back"),
                    callback_data=NavCallback(action=action, version=version).pack(),
                )
            ]
        ]
    )


def location_menu(
    language: str, version: int, translator: Translator = i18n
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=translator.text(language, "search-city"),
                    callback_data=NavCallback(action="city", version=version).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=translator.text(language, "use-location"),
                    callback_data=NavCallback(action="geo", version=version).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=translator.text(language, "back"),
                    callback_data=NavCallback(action="menu", version=version).pack(),
                )
            ],
        ]
    )


def language_menu(
    language: str, version: int, translator: Translator = i18n
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=label,
                callback_data=NavCallback(action="lang", entity=index, version=version).pack(),
            )
        ]
        for index, label in enumerate(
            (
                "🇬🇧 English",
                "🇷🇺 Русский",
                "🇺🇦 Українська",
                "🇹🇷 Türkçe",
                "🇮🇷 فارسی",
                "🇫🇷 Français",
                "🇸🇦 العربية",
            )
        )
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=translator.text(language, "back"),
                callback_data=NavCallback(action="menu", version=version).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def radius_menu(
    language: str,
    version: int,
    *,
    include_entire_city: bool,
    translator: Translator = i18n,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{radius} km",
                callback_data=NavCallback(action="radius", entity=radius, version=version).pack(),
            )
        ]
        for radius in (3, 5, 10, 20)
    ]
    if include_entire_city:
        rows.append(
            [
                InlineKeyboardButton(
                    text=translator.text(language, "entire-city"),
                    callback_data=NavCallback(action="radius", entity=0, version=version).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=translator.text(language, "back"),
                callback_data=NavCallback(action="location", version=version).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
