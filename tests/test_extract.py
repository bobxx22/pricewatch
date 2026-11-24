from decimal import Decimal

import pytest
from bs4 import BeautifulSoup

from scraping import ParseResult
from scraping.extract import (
    clean_text,
    find_json_ld_product,
    first_image,
    first_offer,
    iter_json_ld,
    parse_availability,
    parse_price,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (399, "399.00"),
        (99.9, "99.90"),
        ("399", "399.00"),
        ("719.20", "719.20"),
        ("1 299,50 ₴", "1299.50"),
        ("1 299 грн", "1299.00"),
        ("1,299.50", "1299.50"),
        ("1.299,50", "1299.50"),
        ("1,299", "1299.00"),
        ("12,9", "12.90"),
        ("1.299.000", "1299000.00"),
    ],
)
def test_parse_price(raw: object, expected: str) -> None:
    assert parse_price(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", [None, True, "", "Ціну уточнюйте", "0", "-5", "100-200", "NaN"])
def test_parse_price_rejects_non_prices(raw: object) -> None:
    assert parse_price(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://schema.org/InStock", True),
        ("https://schema.org/InStock/", True),
        ("LimitedAvailability", True),
        ("https://schema.org/OutOfStock", False),
        ("SoldOut", False),
        ("https://schema.org/PreOrder", False),
        ("https://schema.org/SomethingNew", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_availability(raw: object, expected: bool | None) -> None:
    assert parse_availability(raw) is expected


def test_clean_text_collapses_unicode_whitespace() -> None:
    assert clean_text("  Клей для \n плитки  ") == "Клей для плитки"
    assert clean_text(None) == ""


def test_iter_json_ld_unpacks_lists_graph_and_main_entity() -> None:
    soup = BeautifulSoup(
        """
        <script type="application/ld+json">{broken</script>
        <script type="application/ld+json">
          [{"@type": "Organization"}, {"@type": "WebSite"}]
        </script>
        <script type="application/ld+json">
          {"@graph": [{"@type": "WebPage", "mainEntity": {"@type": "Product", "name": "A"}}]}
        </script>
        """,
        "lxml",
    )
    types = [obj.get("@type") for obj in iter_json_ld(soup)]
    assert types == ["Organization", "WebSite", None, "WebPage", "Product"]
    assert find_json_ld_product(soup) == {"@type": "Product", "name": "A"}


def test_first_offer_shapes() -> None:
    assert first_offer({"offers": {"price": 1}}) == {"price": 1}
    assert first_offer({"offers": ["junk", {"price": 2}]}) == {"price": 2}
    assert first_offer({"offers": None}) == {}
    assert first_offer({}) == {}


def test_first_image_shapes() -> None:
    assert first_image(" https://x/a.jpg ") == "https://x/a.jpg"
    assert first_image(["", "https://x/b.jpg"]) == "https://x/b.jpg"
    assert (
        first_image({"@type": "ImageObject", "contentUrl": "https://x/c.jpg"}) == "https://x/c.jpg"
    )
    assert first_image(None) == ""


def test_parse_result_drops_meaningless_old_price() -> None:
    assert ParseResult(title="x", price=Decimal(10), old_price=Decimal(12)).old_price == 12
    assert ParseResult(title="x", price=Decimal(10), old_price=Decimal(9)).old_price is None
    assert ParseResult(title="x", price=None, old_price=Decimal(9)).old_price is None
