"""Reacts to catalog events. Receivers only queue work, after the transaction commits."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.dispatch import receiver

from apps.bot.models import Subscription
from apps.bot.notifications import alert_event
from apps.bot.tasks import dispatch_price_alerts
from apps.catalog.models import Product
from apps.catalog.signals import product_changed


@receiver(product_changed, dispatch_uid="bot.queue_price_alerts")
def queue_price_alerts(sender: type, product: Product, outcome: Any, **kwargs: Any) -> None:
    if not Subscription.objects.filter(product=product, user__is_active=True).exists():
        return
    event = alert_event(outcome)
    transaction.on_commit(lambda: dispatch_price_alerts(product.pk, event))
