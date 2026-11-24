from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from kombu.exceptions import OperationalError

from apps.bot import notifications

logger = logging.getLogger(__name__)


@shared_task(name="bot.send_price_alerts")
def send_price_alerts_task(product_id: int, event: dict[str, Any]) -> int:
    return notifications.send_price_alerts(product_id, event)


def dispatch_price_alerts(product_id: int, event: dict[str, Any]) -> None:
    """Queue the alerts; without a reachable broker, send them right away."""
    try:
        send_price_alerts_task.delay(product_id, event)
    except OperationalError:
        logger.warning("Broker unavailable, sending alerts for product %s now", product_id)
        notifications.send_price_alerts(product_id, event)
