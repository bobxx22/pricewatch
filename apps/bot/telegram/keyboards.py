from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from apps.bot.telegram.callbacks import ShowList, SubscriptionAction

if TYPE_CHECKING:
    from apps.bot.models import Subscription


def subscription_keyboard(
    subscription: Subscription, *, with_back: bool = False
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    target = "🎯 Змінити ціль" if subscription.target_price is not None else "🎯 Цільова ціна"
    builder.button(
        text=target, callback_data=SubscriptionAction(action="target", id=subscription.pk)
    )
    builder.button(
        text="📈 Історія", callback_data=SubscriptionAction(action="history", id=subscription.pk)
    )
    builder.button(text="🔗 Відкрити", url=subscription.product.url)
    builder.button(
        text="🗑 Відписатися", callback_data=SubscriptionAction(action="delete", id=subscription.pk)
    )
    if with_back:
        builder.button(text="⬅️ До списку", callback_data=ShowList())
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def list_keyboard(subscriptions: Sequence[Subscription]) -> InlineKeyboardMarkup | None:
    if not subscriptions:
        return None
    builder = InlineKeyboardBuilder()
    for number, subscription in enumerate(subscriptions, 1):
        builder.button(
            text=str(number), callback_data=SubscriptionAction(action="open", id=subscription.pk)
        )
    builder.adjust(5)
    return builder.as_markup()


def back_to_card_keyboard(subscription: Subscription) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ До товару", callback_data=SubscriptionAction(action="open", id=subscription.pk)
    )
    return builder.as_markup()
