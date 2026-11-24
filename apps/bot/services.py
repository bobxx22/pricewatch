"""Bot use cases. Synchronous and free of Telegram types: the aiogram handlers call them
through sync_to_async, the alert task calls them directly, and tests need no Telegram."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings

from apps.bot.models import Subscription, TelegramUser
from apps.catalog import services as catalog
from apps.catalog.models import PriceSnapshot
from apps.catalog.services import CheckOutcome
from scraping import Fetcher
from scraping.extract import parse_price

URL_RE = re.compile(r"https?://[^\s<>\"'«»]+", re.IGNORECASE)
CLEAR_TARGET_WORDS = {"0", "-", "—", "ні", "нема", "немає", "no", "none"}
ERROR_CODES = {"RobotsDisallowedError": "robots", "ParseError": "not_a_product"}


class SubscribeError(Exception):
    """A link the bot will not track. `code` selects the message shown to the user."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


@dataclass(frozen=True)
class SubscribeResult:
    subscription: Subscription
    created: bool
    outcome: CheckOutcome | None  # None when the product had been checked before


def extract_url(text: str | None) -> str | None:
    match = URL_RE.search(text or "")
    return match.group(0).rstrip(".,;:!?)") if match else None


def register_user(
    *, telegram_id: int, username: str = "", first_name: str = "", language_code: str = ""
) -> TelegramUser:
    """Create the user on first contact; keep their profile fresh and mark them active."""
    fields = {
        "username": username,
        "first_name": first_name,
        "language_code": language_code,
        "is_active": True,
    }
    user, created = TelegramUser.objects.get_or_create(telegram_id=telegram_id, defaults=fields)
    changed = [name for name, value in fields.items() if getattr(user, name) != value]
    if not created and changed:
        for name in changed:
            setattr(user, name, fields[name])
        user.save(update_fields=[*changed, "updated_at"])
    return user


def subscribe(
    user: TelegramUser, raw_url: str, *, fetcher: Fetcher | None = None
) -> SubscribeResult:
    """Track a product link for the user. A product seen for the first time is checked
    right away, so the reply already shows its price; links that are not product pages
    are rejected without leaving anything behind."""
    try:
        url = catalog.normalize_url(raw_url)
    except ValueError as exc:
        raise SubscribeError("invalid_url", str(exc)) from exc

    existing = _subscriptions(user).filter(product__url=url).first()
    if existing is not None:
        return SubscribeResult(existing, created=False, outcome=None)
    if user.subscriptions.count() >= settings.BOT_MAX_SUBSCRIPTIONS:
        raise SubscribeError("limit")

    product, product_created = catalog.add_product(url)
    outcome = None
    if product.last_checked_at is None:
        outcome = catalog.check_product(product, fetcher=fetcher)
        if not outcome.ok and not outcome.retryable:
            if product_created and not product.subscriptions.exists():
                product.delete()
            raise SubscribeError(ERROR_CODES.get(outcome.error_type, "unavailable"), outcome.error)

    subscription, created = Subscription.objects.get_or_create(user=user, product=product)
    return SubscribeResult(_subscriptions(user).get(pk=subscription.pk), created, outcome)


def user_subscriptions(user: TelegramUser) -> list[Subscription]:
    return list(_subscriptions(user).order_by("created_at"))


def get_subscription(user: TelegramUser, subscription_id: int) -> Subscription | None:
    return _subscriptions(user).filter(pk=subscription_id).first()


def unsubscribe(user: TelegramUser, subscription_id: int) -> Subscription | None:
    subscription = get_subscription(user, subscription_id)
    if subscription is not None:
        subscription.delete()
    return subscription


def parse_target_price(text: str) -> Decimal | None:
    """A target price typed by the user. None clears the target; ValueError for non-prices."""
    cleaned = text.strip().lower()
    if cleaned in CLEAR_TARGET_WORDS:
        return None
    price = parse_price(cleaned)
    if price is None:
        raise ValueError(f"Not a price: {text!r}")
    return price


def set_target_price(user: TelegramUser, subscription_id: int, text: str) -> Subscription:
    subscription = get_subscription(user, subscription_id)
    if subscription is None:
        raise Subscription.DoesNotExist(subscription_id)
    subscription.target_price = parse_target_price(text)
    subscription.save(update_fields=["target_price"])
    return subscription


def price_history(subscription: Subscription, limit: int = 10) -> list[PriceSnapshot]:
    return list(subscription.product.snapshots.order_by("-recorded_at")[:limit])


def _subscriptions(user: TelegramUser):
    # Handlers run in an event loop where lazy queries are forbidden: load the shop up front.
    return Subscription.objects.filter(user=user).select_related("product__shop")
