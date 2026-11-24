"""Typed callback data for inline buttons (packed into Telegram's 64-byte callback_data)."""

from aiogram.filters.callback_data import CallbackData


class SubscriptionAction(CallbackData, prefix="sub"):
    action: str  # open | target | history | delete
    id: int


class ShowList(CallbackData, prefix="list"):
    page: int = 0
