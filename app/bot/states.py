from aiogram.fsm.state import State, StatesGroup


class LocationFlow(StatesGroup):
    city_input = State()
    geolocation = State()
    place_selection = State()
    radius_selection = State()


class FilterFlow(StatesGroup):
    price_input = State()
    surface_input = State()


class RestaurantFlow(StatesGroup):
    city_input = State()
    location_input = State()
