"""The generic schema.org parser on shapes beyond a plain JSON-LD Product."""

from decimal import Decimal

import pytest
from bs4 import BeautifulSoup

from scraping import ParseResult, resolve
from scraping.extract import microdata_value, own_property
from scraping.parsers.generic import SchemaOrgParser
from scraping.parsers.rozetka import RozetkaParser
from scraping.parsers.webscraper import WebScraperTestShopParser
from tests.helpers import ROZETKA_URL, WEBSCRAPER_PRODUCT_URL, FakeFetcher, load_html


def test_rozetka_product_group_picks_the_variant_of_the_page() -> None:
    parser = RozetkaParser(fetcher=FakeFetcher({ROZETKA_URL: load_html("rozetka_product.html")}))

    assert parser.parse(ROZETKA_URL) == ParseResult(
        title="Мобільний телефон Samsung Galaxy S25 12/256GB Blueblack (SM-S931BZKGEUC)",
        price=Decimal("36999.00"),
        currency="UAH",
        is_available=True,
        old_price=Decimal("49299.00"),
        sku="525186024",
        image_url="https://content2.rozetka.com.ua/goods/images/base_action/580737957.jpg",
    )


def test_product_group_falls_back_to_the_first_complete_variant() -> None:
    result = SchemaOrgParser().parse_html(
        load_html("rozetka_product.html"), url="https://rozetka.com.ua/ua/other/p1/"
    )

    assert result.sku == "525186024"


def test_product_group_variant_inherits_the_group_name() -> None:
    html = """<script type="application/ld+json">{"@type": "ProductGroup", "name": "Чайник",
      "hasVariant": [{"@type": "Product", "offers": {"price": "999", "priceCurrency": "UAH"}}]}
    </script>"""

    result = SchemaOrgParser().parse_html(html)

    assert (result.title, result.price) == ("Чайник", Decimal("999.00"))


def test_microdata_product_ignores_names_of_nested_items() -> None:
    parser = WebScraperTestShopParser(
        fetcher=FakeFetcher({WEBSCRAPER_PRODUCT_URL: load_html("webscraper_product.html")})
    )

    assert parser.parse(WEBSCRAPER_PRODUCT_URL) == ParseResult(
        title="Asus VivoBook X441NA-GA190",
        price=Decimal("295.99"),
        currency="USD",
        is_available=None,
        image_url="https://webscraper.io/images/test-sites/e-commerce/items/cart2.png",
    )


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<meta itemprop="x" content=" 12 ">', "12"),
        ('<link itemprop="x" href="https://schema.org/InStock">', "https://schema.org/InStock"),
        ('<img itemprop="x" src="/a.png">', "/a.png"),
        ('<data itemprop="x" value="719.20">719,20 ₴</data>', "719.20"),
        ('<span itemprop="x" content="5">five</span>', "5"),
        ('<span itemprop="x">  Клей для плитки </span>', "Клей для плитки"),
    ],
)
def test_microdata_value_follows_the_html_rules(html: str, expected: str) -> None:
    element = BeautifulSoup(html, "lxml").select_one('[itemprop="x"]')

    assert microdata_value(element) == expected


def test_own_property_skips_nested_scopes() -> None:
    soup = BeautifulSoup(load_html("webscraper_product.html"), "lxml")
    product = soup.select_one('[itemtype$="schema.org/Product"]')

    assert microdata_value(own_property(product, "name")) == "Asus VivoBook X441NA-GA190"
    assert own_property(product, "reviewCount") is None  # belongs to aggregateRating


@pytest.mark.parametrize(
    ("url", "parser_cls"),
    [
        (ROZETKA_URL, RozetkaParser),
        (WEBSCRAPER_PRODUCT_URL, WebScraperTestShopParser),
    ],
)
def test_new_shops_are_registered(url: str, parser_cls: type) -> None:
    assert resolve(url)[1] is parser_cls
