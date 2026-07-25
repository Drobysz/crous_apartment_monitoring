from aiogram.fsm.state import State, StatesGroup


class LocationFlow(StatesGroup):
    city_input = State()
    geolocation = State()
    place_selection = State()
    radius_selection = State()
