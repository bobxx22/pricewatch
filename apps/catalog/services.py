"""Business logic for products and price checks.

Admin actions, management commands and Celery tasks all go through these functions,
so the rules live in one place.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import PriceSnapshot, Product, Shop
from apps.catalog.signals import product_changed
from scraping import Fetcher, HttpFetcher, ParseResult, ScrapingError, get_parser, resolve
from scraping.browser import PlaywrightFetcher
from scraping.listings import ListingItem, listing_spec_for, scan_listing

logger = logging.getLogger(__name__)

TRACKING_PARAM_PREFIXES = ("utm_", "gclid", "fbclid", "gad_source", "srsltid")
MAX_ERROR_LENGTH = 1000


@dataclass(frozen=True)
class CheckOutcome:
    """What a single price check found, compared with the previous state."""

    product_id: int
    ok: bool
    price: Decimal | None = None
    previous_price: Decimal | None = None
    is_available: bool | None = None
    was_available: bool | None = None
    changed: bool = False
    error: str = ""
    error_type: str = ""  # ScrapingError subclass name, e.g. "RobotsDisallowedError"
    retryable: bool = False

    @property
    def price_dropped(self) -> bool:
        return (
            self.ok
            and self.price is not None
            and self.previous_price is not None
            and self.price < self.previous_price
        )

    @property
    def back_in_stock(self) -> bool:
        return self.ok and self.was_available is False and self.is_available is True

    def as_dict(self) -> dict[str, Any]:
        data = {
            key: str(value) if isinstance(value, Decimal) else value
            for key, value in asdict(self).items()
        }
        return data | {"price_dropped": self.price_dropped, "back_in_stock": self.back_in_stock}


def normalize_url(url: str) -> str:
    """Drop the fragment and tracking parameters so one product is not tracked twice."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"Not a valid http(s) URL: {url!r}")
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(TRACKING_PARAM_PREFIXES)
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(query), "")
    )


def build_fetcher() -> HttpFetcher:
    return HttpFetcher(
        user_agent=settings.SCRAPER_USER_AGENT,
        timeout=settings.SCRAPER_TIMEOUT,
        respect_robots_txt=settings.SCRAPER_RESPECT_ROBOTS_TXT,
    )


def build_browser_fetcher() -> PlaywrightFetcher:
    """A headless browser; close it after use (it is a context manager)."""
    return PlaywrightFetcher(
        user_agent=settings.SCRAPER_USER_AGENT,
        timeout=settings.PLAYWRIGHT_TIMEOUT,
        respect_robots_txt=settings.SCRAPER_RESPECT_ROBOTS_TXT,
        channel=settings.PLAYWRIGHT_CHANNEL,
    )


def scan_category(url: str, *, pages: int = 1) -> list[ListingItem]:
    """Product cards from a category page: plain HTTP for server-rendered pagination,
    a headless browser for listings that grow through a "load more" button."""
    spec = listing_spec_for(url)  # ValueError for shops without listing support
    http = build_fetcher()
    if not spec.needs_browser:
        return scan_listing(url, pages=pages, http=http, delay=settings.SCRAPER_DELAY)
    with build_browser_fetcher() as browser:
        return scan_listing(url, pages=pages, http=http, browser=browser)


def get_or_create_shop(url: str) -> Shop:
    domain, parser_cls = resolve(url)
    shop, _ = Shop.objects.get_or_create(
        domain=domain, defaults={"name": parser_cls.shop_name or domain}
    )
    return shop


def add_product(url: str) -> tuple[Product, bool]:
    """Start tracking a product URL. Returns (product, created)."""
    url = normalize_url(url)
    return Product.objects.get_or_create(url=url, defaults={"shop": get_or_create_shop(url)})


def check_product(product: Product, *, fetcher: Fetcher | None = None) -> CheckOutcome:
    """Fetch the product page, update the product and record a snapshot if anything changed.

    Scraping errors are stored on the product instead of being raised;
    `CheckOutcome.retryable` tells the caller whether a retry makes sense.
    """
    parser = get_parser(product.url, fetcher=fetcher or build_fetcher())
    try:
        result = parser.parse(product.url)
    except ScrapingError as exc:
        logger.warning("Check failed for product %s: %s", product.pk, exc)
        record_failure(product, str(exc))
        return CheckOutcome(
            product_id=product.pk,
            ok=False,
            previous_price=product.price,
            was_available=product.is_available,
            error=str(exc),
            error_type=type(exc).__name__,
            retryable=exc.retryable,
        )
    return apply_result(product, result)


def apply_result(product: Product, result: ParseResult) -> CheckOutcome:
    now = timezone.now()
    with transaction.atomic():
        # Lock the row so two workers checking the same product can't interleave.
        previous = (
            Product.objects.select_for_update()
            .only("price", "old_price", "is_available", "last_checked_at")
            .get(pk=product.pk)
        )
        changed = (result.price, result.old_price, result.is_available) != (
            previous.price,
            previous.old_price,
            previous.is_available,
        )
        first_check = previous.last_checked_at is None

        product.title = result.title or product.title
        product.sku = result.sku or product.sku
        product.image_url = result.image_url or product.image_url
        product.currency = result.currency
        product.price = result.price
        product.old_price = result.old_price
        product.is_available = result.is_available
        product.last_checked_at = now
        product.next_check_at = now + settings.PRICE_CHECK_INTERVAL
        product.last_error = ""
        product.save(
            update_fields=[
                "title",
                "sku",
                "image_url",
                "currency",
                "price",
                "old_price",
                "is_available",
                "last_checked_at",
                "next_check_at",
                "last_error",
                "updated_at",
            ]
        )
        if changed or first_check:
            PriceSnapshot.objects.create(
                product=product,
                price=result.price,
                old_price=result.old_price,
                is_available=result.is_available,
                recorded_at=now,
            )

    outcome = CheckOutcome(
        product_id=product.pk,
        ok=True,
        price=result.price,
        previous_price=previous.price,
        is_available=result.is_available,
        was_available=previous.is_available,
        changed=changed,
    )
    if outcome.price_dropped or outcome.back_in_stock:
        product_changed.send(sender=Product, product=product, outcome=outcome)
    return outcome


def record_failure(product: Product, error: str) -> None:
    now = timezone.now()
    product.last_checked_at = now
    product.next_check_at = now + settings.PRICE_CHECK_INTERVAL
    product.last_error = error[:MAX_ERROR_LENGTH]
    product.save(update_fields=["last_checked_at", "next_check_at", "last_error", "updated_at"])


def claim_due_products(limit: int, now: datetime | None = None) -> list[int]:
    """Pick products that are due and move their next check forward.

    Claiming before queueing means the next scheduler tick skips products whose
    checks are still waiting in the queue, so nothing is checked twice.
    """
    now = now or timezone.now()
    with transaction.atomic():
        ids = list(
            Product.objects.due_for_check(now)
            .order_by("next_check_at")
            .values_list("pk", flat=True)[:limit]
        )
        Product.objects.filter(pk__in=ids).update(next_check_at=now + settings.PRICE_CHECK_INTERVAL)
    return ids
