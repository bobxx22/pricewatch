"""Celery tasks. Thin wrappers around services.py: no business logic here."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.conf import settings
from kombu.exceptions import OperationalError

from apps.catalog import services
from apps.catalog.models import Product

logger = logging.getLogger(__name__)


def queue_check(product_id: int) -> bool:
    """Queue a price check. Without a reachable broker, check right away instead.

    Returns True when the check was queued, False when it ran in-process.
    """
    try:
        check_product_task.delay(product_id)
    except OperationalError:
        logger.warning("Broker unavailable, checking product %s synchronously", product_id)
        product = Product.objects.select_related("shop").get(pk=product_id)
        services.check_product(product)
        return False
    return True


@shared_task(name="catalog.enqueue_due_checks")
def enqueue_due_checks() -> int:
    """Run by celery beat: queue one check per due product."""
    product_ids = services.claim_due_products(limit=settings.PRICE_CHECK_BATCH_SIZE)
    for product_id in product_ids:
        check_product_task.delay(product_id)
    return len(product_ids)


@shared_task(
    bind=True,
    name="catalog.check_product",
    max_retries=3,
    rate_limit=settings.SCRAPER_RATE_LIMIT,
)
def check_product_task(self, product_id: int) -> dict[str, Any]:
    product = Product.objects.select_related("shop").filter(pk=product_id, is_active=True).first()
    if product is None:
        return {"product_id": product_id, "skipped": True}

    outcome = services.check_product(product)
    if outcome.retryable and self.request.retries < self.max_retries:
        # 1, 2, 4 minutes: gives a flaky shop time to recover.
        raise self.retry(countdown=60 * 2**self.request.retries)
    return outcome.as_dict()
