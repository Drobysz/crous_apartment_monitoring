from __future__ import annotations

from app.core.i18n import Translator, i18n
from app.restaurants.models import Restaurant, RestaurantMenu


def restaurant_information(
    restaurant: Restaurant, language: str, translator: Translator = i18n
) -> str:
    rows = [restaurant.name]
    values = (
        ("restaurant-address", restaurant.address),
        (
            "restaurant-status",
            translator.text(
                language, "restaurant-open" if restaurant.is_open else "restaurant-closed"
            )
            if restaurant.is_open is not None
            else None,
        ),
        ("restaurant-hours", "\n".join(restaurant.hours) or None),
        ("restaurant-payment", ", ".join(restaurant.payment_methods) or None),
        ("restaurant-transport", restaurant.transport),
        ("restaurant-phone", restaurant.phone),
        ("restaurant-email", restaurant.email),
    )
    rows.extend(translator.text(language, key, value=value) for key, value in values if value)
    return "\n".join(rows)


def menu_text(menu: RestaurantMenu, language: str, translator: Translator = i18n) -> str:
    heading = translator.text(
        language, "restaurant-menu-date", value=menu.date.strftime("%d/%m/%Y")
    )
    if menu.state != "available":
        return heading + "\n\n" + translator.text(language, f"restaurant-menu-{menu.state}")
    return heading + "\n\n" + "\n".join(f"• {item}" for item in menu.items)
