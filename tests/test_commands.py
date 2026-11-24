from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.catalog.models import Product, Shop
from tests.helpers import PROM_URL, FakeFetcher, load_html

pytestmark = pytest.mark.django_db


def run(*args: str) -> str:
    out = StringIO()
    call_command(*args, stdout=out, stderr=StringIO())
    return out.getvalue()


def test_add_product_with_check(use_fake_fetcher: FakeFetcher) -> None:
    use_fake_fetcher.pages[PROM_URL] = load_html("prom_product.html")

    output = run("add_product", f"{PROM_URL}#reviews", "--check")

    assert "Added: #" in output
    assert "399.00 UAH, in stock" in output
    assert Product.objects.get().url == PROM_URL


def test_add_product_reports_invalid_urls_and_keeps_valid_ones() -> None:
    with pytest.raises(CommandError, match="1 of 2"):
        run("add_product", "not-a-url", PROM_URL)

    assert Product.objects.count() == 1


def test_check_prices_checks_only_due_products(
    prom_shop: Shop, use_fake_fetcher: FakeFetcher
) -> None:
    Product.objects.create(shop=prom_shop, url=PROM_URL)
    later = timezone.now() + timedelta(hours=1)
    Product.objects.create(shop=prom_shop, url=f"{PROM_URL}?later", next_check_at=later)
    use_fake_fetcher.pages[PROM_URL] = load_html("prom_product.html")

    output = run("check_prices", "--delay", "0")

    assert use_fake_fetcher.requested == [PROM_URL]
    assert "Checked 1, failed 0." in output


def test_check_prices_all_reports_failures(prom_shop: Shop, use_fake_fetcher: FakeFetcher) -> None:
    Product.objects.create(shop=prom_shop, url=PROM_URL)
    broken = Product.objects.create(shop=prom_shop, url=f"{PROM_URL}?gone")
    use_fake_fetcher.pages[PROM_URL] = load_html("prom_product.html")

    output = run("check_prices", "--all", "--delay", "0")

    assert f"FAIL #{broken.pk}" in output
    assert "Checked 2, failed 1." in output


def test_check_prices_with_nothing_due() -> None:
    assert "Nothing to check." in run("check_prices")


def test_scan_category_lists_cheapest_first_and_can_track(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    from scraping.listings import ListingItem

    items = [
        ListingItem("Дорогий", "https://rozetka.com.ua/ua/a/p1/", Decimal(900)),
        ListingItem(
            "Дешевий", "https://rozetka.com.ua/ua/b/p2/", Decimal("100.00"), Decimal("150.00")
        ),
        ListingItem("Без ціни", "https://rozetka.com.ua/ua/c/p3/", None),
    ]
    calls: list[tuple[str, int]] = []

    def fake_scan(url: str, *, pages: int) -> list[ListingItem]:
        calls.append((url, pages))
        return list(items)

    monkeypatch.setattr("apps.catalog.services.scan_category", fake_scan)

    output = run(
        "scan_category",
        "https://rozetka.com.ua/ua/x/c1/",
        "--pages",
        "2",
        "--limit",
        "2",
        "--track",
    )

    assert calls == [("https://rozetka.com.ua/ua/x/c1/", 2)]
    assert output.index("Дешевий") < output.index("Дорогий")
    assert "Без ціни" not in output
    assert "(was 150.00)" in output
    assert "Tracking 2 products (2 new)." in output
    assert set(Product.objects.values_list("title", flat=True)) == {""}
    assert Product.objects.count() == 2


def test_scan_category_max_price_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from decimal import Decimal

    from scraping.listings import ListingItem

    monkeypatch.setattr(
        "apps.catalog.services.scan_category",
        lambda url, *, pages: [ListingItem("A", "https://rozetka.com.ua/ua/a/p1/", Decimal(500))],
    )
    assert "Found 0 products" in run(
        "scan_category", "https://rozetka.com.ua/ua/x/c1/", "--max-price", "100"
    )


def test_scan_category_rejects_shops_without_listing_support() -> None:
    with pytest.raises(CommandError, match="not supported"):
        run("scan_category", "https://prom.ua/ua/Category")


def test_seed_demo_creates_an_inactive_demo_shop_and_clears_it() -> None:
    output = run("seed_demo")

    shop = Shop.objects.get(domain="demo.pricewatch.example")
    assert "Created 8 demo products" in output
    assert shop.is_active is False
    assert shop.products.count() == 8
    assert all(p.snapshots.count() >= 2 for p in shop.products.all())
    assert not Product.objects.due_for_check().exists()  # never scraped

    run("seed_demo", "--clear")
    assert not Shop.objects.filter(domain="demo.pricewatch.example").exists()
