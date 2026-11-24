from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.utils import timezone

from apps.catalog.models import Product, Shop
from apps.catalog.services import (
    add_product,
    apply_result,
    check_product,
    claim_due_products,
    normalize_url,
)
from scraping import FetchError, ParseResult
from tests.helpers import PROM_URL, FakeFetcher, load_html

pytestmark = pytest.mark.django_db


def test_normalize_url_drops_fragment_and_tracking_params() -> None:
    url = " https://Prom.UA/ua/p1.html?utm_source=tg&color=red&gclid=1#reviews "

    assert normalize_url(url) == "https://prom.ua/ua/p1.html?color=red"


@pytest.mark.parametrize("url", ["prom.ua/p1", "ftp://prom.ua/x", "", "https://"])
def test_normalize_url_rejects_invalid_urls(url: str) -> None:
    with pytest.raises(ValueError, match="valid"):
        normalize_url(url)


def test_add_product_detects_shop_and_is_idempotent() -> None:
    product, created = add_product(f"{PROM_URL}?utm_source=tg")
    again, created_again = add_product(PROM_URL)

    assert created is True
    assert created_again is False
    assert again.pk == product.pk
    assert product.url == PROM_URL
    assert (product.shop.domain, product.shop.name) == ("prom.ua", "Prom.ua")


def test_add_product_from_unknown_shop_uses_hostname() -> None:
    product, _ = add_product("https://www.shop.example.com/item/1")

    assert product.shop.domain == "shop.example.com"
    assert product.shop.name == "shop.example.com"


def test_first_check_fills_product_and_records_snapshot(prom_product: Product) -> None:
    fetcher = FakeFetcher({PROM_URL: load_html("prom_product.html")})

    outcome = check_product(prom_product, fetcher=fetcher)

    assert outcome.ok
    assert outcome.changed
    assert not outcome.price_dropped
    assert not outcome.back_in_stock
    prom_product.refresh_from_db()
    assert prom_product.title.startswith("Оливкова олія Monini")
    assert (prom_product.price, prom_product.old_price) == (Decimal("399.00"), Decimal("935.00"))
    assert prom_product.discount_percent == 57
    assert prom_product.is_available is True
    assert prom_product.sku == "80053835"
    assert (
        prom_product.next_check_at == prom_product.last_checked_at + settings.PRICE_CHECK_INTERVAL
    )
    assert prom_product.snapshots.count() == 1


def test_unchanged_product_adds_no_snapshot(prom_product: Product) -> None:
    fetcher = FakeFetcher({PROM_URL: load_html("prom_product.html")})

    check_product(prom_product, fetcher=fetcher)
    second = check_product(prom_product, fetcher=fetcher)

    assert second.ok
    assert not second.changed
    assert prom_product.snapshots.count() == 1


def test_price_drop_and_restock_are_detected(prom_product: Product) -> None:
    apply_result(prom_product, ParseResult(title="Oil", price=Decimal(500), is_available=False))
    outcome = apply_result(
        prom_product, ParseResult(title="Oil", price=Decimal(399), is_available=True)
    )

    assert outcome.price_dropped
    assert outcome.back_in_stock
    assert outcome.previous_price == Decimal("500.00")
    history = prom_product.snapshots.order_by("pk").values_list("price", "is_available")
    assert list(history) == [(Decimal("500.00"), False), (Decimal("399.00"), True)]


def test_failure_is_stored_and_marked_retryable(prom_product: Product) -> None:
    fetcher = FakeFetcher({PROM_URL: FetchError("HTTP 503: shop is down", retryable=True)})

    outcome = check_product(prom_product, fetcher=fetcher)

    assert not outcome.ok
    assert outcome.retryable
    prom_product.refresh_from_db()
    assert "HTTP 503" in prom_product.last_error
    assert prom_product.last_checked_at is not None
    assert prom_product.snapshots.count() == 0


def test_parse_error_is_not_retryable_and_success_clears_it(prom_product: Product) -> None:
    fetcher = FakeFetcher({PROM_URL: load_html("no_product.html")})
    failed = check_product(prom_product, fetcher=fetcher)

    fetcher.pages[PROM_URL] = load_html("prom_product.html")
    check_product(prom_product, fetcher=fetcher)

    assert not failed.ok
    assert not failed.retryable
    prom_product.refresh_from_db()
    assert prom_product.last_error == ""


def test_claim_due_products(prom_shop: Shop) -> None:
    now = timezone.now()
    hour = timedelta(hours=1)
    oldest = Product.objects.create(shop=prom_shop, url=f"{PROM_URL}?a", next_check_at=now - hour)
    due = Product.objects.create(shop=prom_shop, url=f"{PROM_URL}?b", next_check_at=now)
    Product.objects.create(shop=prom_shop, url=f"{PROM_URL}?later", next_check_at=now + hour)
    Product.objects.create(
        shop=prom_shop, url=f"{PROM_URL}?off", next_check_at=now - hour, is_active=False
    )
    paused = Shop.objects.create(name="Paused", domain="paused.example.com", is_active=False)
    Product.objects.create(shop=paused, url="https://paused.example.com/1", next_check_at=now)

    assert claim_due_products(limit=1, now=now) == [oldest.pk]
    assert claim_due_products(limit=10, now=now) == [due.pk]
    assert claim_due_products(limit=10, now=now) == []
    due.refresh_from_db()
    assert due.next_check_at == now + settings.PRICE_CHECK_INTERVAL
