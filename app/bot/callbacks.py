from aiogram.filters.callback_data import CallbackData


class NavCallback(CallbackData, prefix="n"):
    action: str
    entity: int = 0
    page: int = 0
    version: int = 0
