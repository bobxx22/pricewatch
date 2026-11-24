from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.bot import services
from apps.bot.models import Subscription, TelegramUser
from apps.catalog.models import PriceSnapshot, Product, Shop
from scraping import FetchError, RobotsDisallowedError
from tests.helpers import PROM_URL, FakeFetcher, load_html

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"Глянь {PROM_URL}, класна олія!", PROM_URL),
        (f"<{PROM_URL}>", PROM_URL),
        ("https://rozetka.com.ua/ua/x/p1/).", "https://rozetka.com.ua/ua/x/p1/"),
        ("без посилання", None),
        (None, None),
    ],
)
def test_extract_url(text: str | None, expected: str | None) -> None:
    assert services.extract_url(text) == expected


def test_register_user_creates_updates_and_reactivates(db: None) -> None:
    user = services.register_user(telegram_id=7, username="old", first_name="Олег")
    TelegramUser.objects.filter(pk=user.pk).update(is_active=False)

    again = services.register_user(telegram_id=7, username="new", first_name="Олег")

    assert again.pk == user.pk
    assert again.username == "new"
    assert again.is_active is True
    assert TelegramUser.objects.count() == 1


def test_subscribe_checks_a_new_product_right_away(
    tg_user: TelegramUser, use_fake_fetcher: FakeFetcher
) -> None:
    use_fake_fetcher.pages[PROM_URL] = load_html("prom_product.html")

    result = services.subscribe(tg_user, f"{PROM_URL}?utm_source=telegram")

    assert result.created is True
    assert result.outcome is not None
    assert result.outcome.ok
    assert result.subscription.product.price == Decimal("399.00")
    assert result.subscription.product.shop.name == "Prom.ua"


def test_subscribing_twice_returns_the_same_subscription(
    tg_user: TelegramUser, use_fake_fetcher: FakeFetcher
) -> None:
    use_fake_fetcher.pages[PROM_URL] = load_html("prom_product.html")
    first = services.subscribe(tg_user, PROM_URL)

    second = services.subscribe(tg_user, PROM_URL)

    assert second.created is False
    assert second.outcome is None
    assert second.subscription.pk == first.subscription.pk
    assert len(use_fake_fetcher.requested) == 1


def test_an_already_checked_product_is_not_fetched_again(
    tg_user: TelegramUser, prom_product: Product, use_fake_fetcher: FakeFetcher
) -> None:
    Product.objects.filter(pk=prom_product.pk).update(last_checked_at=timezone.now())

    result = services.subscribe(tg_user, PROM_URL)

    assert result.created is True
    assert result.outcome is None
    assert use_fake_fetcher.requested == []


@pytest.mark.parametrize(
    ("page", "code"),
    [
        (load_html("no_product.html"), "not_a_product"),
        (RobotsDisallowedError("robots.txt disallows it"), "robots"),
        (FetchError("Page not found (HTTP 404)", retryable=False), "unavailable"),
    ],
)
def test_links_that_are_not_trackable_leave_nothing_behind(
    tg_user: TelegramUser, use_fake_fetcher: FakeFetcher, page: object, code: str
) -> None:
    use_fake_fetcher.pages[PROM_URL] = page

    with pytest.raises(services.SubscribeError) as error:
        services.subscribe(tg_user, PROM_URL)

    assert error.value.code == code
    assert not Product.objects.exists()
    assert not Subscription.objects.exists()


def test_a_shop_that_is_down_is_retried_later(
    tg_user: TelegramUser, use_fake_fetcher: FakeFetcher
) -> None:
    use_fake_fetcher.pages[PROM_URL] = FetchError("HTTP 503", retryable=True)

    result = services.subscribe(tg_user, PROM_URL)

    assert result.created is True
    assert result.outcome is not None
    assert not result.outcome.ok
    assert result.subscription.product.last_error == "HTTP 503"


def test_invalid_url_and_subscription_limit(
    tg_user: TelegramUser, subscription: Subscription, settings: object
) -> None:
    settings.BOT_MAX_SUBSCRIPTIONS = 1  # type: ignore[attr-defined]

    with pytest.raises(services.SubscribeError) as invalid:
        services.subscribe(tg_user, "prom.ua/no-scheme")
    with pytest.raises(services.SubscribeError) as limit:
        services.subscribe(tg_user, "https://prom.ua/ua/p2-other.html")

    assert invalid.value.code == "invalid_url"
    assert limit.value.code == "limit"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("350", Decimal("350.00")), ("1 299,50 грн", Decimal("1299.50")), ("0", None), ("ні", None)],
)
def test_target_price(subscription: Subscription, text: str, expected: Decimal | None) -> None:
    updated = services.set_target_price(subscription.user, subscription.pk, text)

    assert updated.target_price == expected


def test_target_price_rejects_text_and_other_peoples_subscriptions(
    subscription: Subscription,
) -> None:
    stranger = TelegramUser.objects.create(telegram_id=2)

    with pytest.raises(ValueError, match="Not a price"):
        services.set_target_price(subscription.user, subscription.pk, "дешевше")
    with pytest.raises(Subscription.DoesNotExist):
        services.set_target_price(stranger, subscription.pk, "100")


def test_unsubscribe_only_own(subscription: Subscription) -> None:
    stranger = TelegramUser.objects.create(telegram_id=2)

    assert services.unsubscribe(stranger, subscription.pk) is None
    removed = services.unsubscribe(subscription.user, subscription.pk)

    assert removed is not None
    assert removed.product.url == PROM_URL
    assert not Subscription.objects.exists()


def test_price_history_newest_first(subscription: Subscription) -> None:
    now = timezone.now()
    for days in (3, 2, 1):
        PriceSnapshot.objects.create(
            product=subscription.product, price=days * 100, recorded_at=now - timedelta(days=days)
        )

    history = services.price_history(subscription, limit=2)

    assert [s.price for s in history] == [Decimal(100), Decimal(200)]


@pytest.mark.parametrize(
    ("target", "dropped", "restocked", "price", "expected"),
    [
        (None, True, False, Decimal(90), True),
        (Decimal(95), True, False, Decimal(90), True),
        (Decimal(80), True, False, Decimal(90), False),
        (Decimal(80), False, True, Decimal(90), True),
        (None, False, False, Decimal(90), False),
    ],
)
def test_wants_alert(
    target: Decimal | None, dropped: bool, restocked: bool, price: Decimal, expected: bool
) -> None:
    subscription = Subscription(target_price=target)

    assert (
        subscription.wants_alert(price_dropped=dropped, back_in_stock=restocked, price=price)
        is expected
    )


def test_texts_escape_shop_data(subscription: Subscription) -> None:
    from apps.bot import texts

    Product.objects.filter(pk=subscription.product_id).update(
        title="<b>Олія</b> & Co", price=Decimal("399.50"), old_price=Decimal(500), is_available=True
    )
    Shop.objects.filter(pk=subscription.product.shop_id).update(name="Prom <ua>")
    subscription = services.get_subscription(subscription.user, subscription.pk)

    card = texts.card(subscription)

    assert "&lt;b&gt;Олія&lt;/b&gt; &amp; Co" in card
    assert "Prom &lt;ua&gt;" in card
    assert "399,50 ₴" in card
    assert "−20%" in card
