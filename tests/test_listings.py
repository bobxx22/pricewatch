from decimal import Decimal

import pytest

from scraping.listings import (
    ListingItem,
    listing_spec_for,
    parse_listing,
    rozetka_page_url,
    scan_listing,
)
from tests.helpers import (
    ROZETKA_CATEGORY_URL,
    WEBSCRAPER_LISTING_URL,
    FakeFetcher,
    load_html,
)


def test_rozetka_tiles_without_duplicates_or_banners() -> None:
    items = parse_listing(
        load_html("rozetka_category.html"),
        listing_spec_for(ROZETKA_CATEGORY_URL),
        ROZETKA_CATEGORY_URL,
    )

    assert [item.price for item in items] == [
        Decimal("36999.00"),
        Decimal("9499.00"),
        Decimal("2555.00"),
    ]
    assert items[0] == ListingItem(
        title="Мобільний телефон Samsung Galaxy S25 12/256GB Blueblack (SM-S931BZKGEUC)",
        url="https://rozetka.com.ua/ua/samsung-sm-s931bzkgeuc/p525186024/",
        price=Decimal("36999.00"),
        old_price=Decimal("49299.00"),
        currency="UAH",
        image_url="https://content2.rozetka.com.ua/goods/images/big_tile/580737957.jpg",
    )


def test_webscraper_cards_use_full_titles_and_absolute_urls() -> None:
    items = parse_listing(
        load_html("webscraper_listing.html"),
        listing_spec_for(WEBSCRAPER_LISTING_URL),
        WEBSCRAPER_LISTING_URL,
    )

    assert [(i.title, i.price, i.currency) for i in items] == [
        ("Asus VivoBook X441NA-GA190", Decimal("295.99"), "USD"),
        ("Prestigio SmartBook 133S Dark Grey", Decimal("299.00"), "USD"),
    ]
    assert items[0].url == "https://webscraper.io/test-sites/e-commerce/more/product/60"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (ROZETKA_CATEGORY_URL, f"{ROZETKA_CATEGORY_URL}page=3/"),
        ("https://rozetka.com.ua/ua/mobile-phones/c80003", f"{ROZETKA_CATEGORY_URL}page=3/"),
        (f"{ROZETKA_CATEGORY_URL}page=2/", f"{ROZETKA_CATEGORY_URL}page=3/"),
        (f"{ROZETKA_CATEGORY_URL}page=1,2/", f"{ROZETKA_CATEGORY_URL}page=3/"),
        (f"{ROZETKA_CATEGORY_URL}?sort=cheap", f"{ROZETKA_CATEGORY_URL}page=3/"),
    ],
)
def test_rozetka_page_url(url: str, expected: str) -> None:
    assert rozetka_page_url(url, 3) == expected


def test_unsupported_listing_domain() -> None:
    with pytest.raises(ValueError, match="not supported"):
        listing_spec_for("https://prom.ua/ua/Maslo-rastitelnoe")


def test_server_paginated_listing_is_read_over_http_until_an_empty_page() -> None:
    html = load_html("rozetka_category.html")
    fetcher = FakeFetcher(
        {
            ROZETKA_CATEGORY_URL: html,
            f"{ROZETKA_CATEGORY_URL}page=2/": html.replace("p600000001", "p700000001"),
            f"{ROZETKA_CATEGORY_URL}page=3/": "<html><body>Кінець</body></html>",
        }
    )

    items = scan_listing(ROZETKA_CATEGORY_URL, pages=5, http=fetcher)

    assert fetcher.requested == [
        ROZETKA_CATEGORY_URL,
        f"{ROZETKA_CATEGORY_URL}page=2/",
        f"{ROZETKA_CATEGORY_URL}page=3/",
    ]
    assert len(items) == 4  # 3 + one new product on page 2; repeats are dropped


def test_load_more_listing_requires_a_browser() -> None:
    with pytest.raises(ValueError, match="need a browser"):
        scan_listing(WEBSCRAPER_LISTING_URL, http=FakeFetcher())


def test_load_more_listing_goes_through_the_browser() -> None:
    class FakeBrowser:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def get(self, url: str, *, wait_for: str | None = None, actions=None) -> str:
            self.calls.append((url, wait_for))
            return load_html("webscraper_listing.html")

    browser = FakeBrowser()
    items = scan_listing(WEBSCRAPER_LISTING_URL, pages=2, http=FakeFetcher(), browser=browser)

    assert browser.calls == [(WEBSCRAPER_LISTING_URL, ".thumbnail")]
    assert len(items) == 2
