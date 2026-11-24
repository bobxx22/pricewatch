"""Price alerts: decide who wants to hear about a change and send them a message."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from apps.bot import telegram_api, texts
from apps.bot.models import Subscription, TelegramUser
from apps.bot.telegram.keyboards import subscription_keyboard

logger = logging.getLogger(__name__)


def alert_event(outcome: Any) -> dict[str, Any]:
    """A JSON-safe description of a price change, small enough for a Celery message."""
    return {
        "price": str(outcome.price) if outcome.price is not None else None,
        "previous_price": str(outcome.previous_price)
        if outcome.previous_price is not None
        else None,
        "price_dropped": outcome.price_dropped,
        "back_in_stock": outcome.back_in_stock,
    }


def send_price_alerts(product_id: int, event: dict[str, Any]) -> int:
    """Message every subscriber who wants this change. Returns how many were sent."""
    client = telegram_api.get_client()
    if client is None:
        logger.warning("TELEGRAM_BOT_TOKEN is not set; alerts for product %s skipped", product_id)
        return 0

    price = Decimal(event["price"]) if event.get("price") else None
    subscriptions = Subscription.objects.filter(
        product_id=product_id, user__is_active=True
    ).select_related("user", "product__shop")
    sent = 0
    for subscription in subscriptions:
        if not subscription.wants_alert(
            price_dropped=bool(event.get("price_dropped")),
            back_in_stock=bool(event.get("back_in_stock")),
            price=price,
        ):
            continue
        markup = subscription_keyboard(subscription).model_dump(mode="json", exclude_none=True)
        try:
            client.send_message(
                subscription.user.telegram_id,
                texts.price_alert(subscription, event),
                reply_markup=markup,
            )
        except telegram_api.BotBlockedError:
            TelegramUser.objects.filter(pk=subscription.user_id).update(is_active=False)
            logger.info("User %s blocked the bot; marked inactive", subscription.user_id)
        except telegram_api.TelegramApiError as exc:
            logger.warning("Alert to user %s failed: %s", subscription.user_id, exc)
        else:
            sent += 1
    return sent
