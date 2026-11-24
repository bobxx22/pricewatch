from decimal import Decimal

import pytest

from scraping import ParseError, ParseResult
from scraping.parsers.epicentr import EpicentrParser
from scraping.parsers.generic import SchemaOrgParser
from scraping.parsers.prom import PromParser
from tests.helpers import EPICENTR_URL, PROM_URL, FakeFetcher, load_html

OIL = "Оливкова олія Monini Extra Virgin Classico 1 л (80053835)"
GLUE = "Клей для плитки Ceresit CM 117 Flex 25 кг"


def test_prom_product_with_discount() -> None:
    parser = PromParser(fetcher=FakeFetcher({PROM_URL: load_html("prom_product.html")}))

    assert parser.parse(PROM_URL) == ParseResult(
        title=OIL,
        price=Decimal("399.00"),
        currency="UAH",
        is_available=True,
        old_price=Decimal("935.00"),
        sku="80053835",
        image_url="https://images.prom.ua/7177403873_w640_h640_olivkovoe-maslo-monini.jpg",
    )


def test_prom_out_of_stock() -> None:
    result = PromParser().parse_html(load_html("prom_out_of_stock.html"))

    assert result.is_available is False
    assert result.price == Decimal("419.00")
    assert result.old_price is None


def test_epicentr_product_with_discount() -> None:
    parser = EpicentrParser(fetcher=FakeFetcher({EPICENTR_URL: load_html("epicentr_product.html")}))

    assert parser.parse(EPICENTR_URL) == ParseResult(
        title=GLUE,
        price=Decimal("719.20"),
        currency="UAH",
        is_available=True,
        old_price=Decimal("899.00"),
        sku="60301004",
        image_url="https://cdn.27.ua/799/6c/fb/27899_2.jpeg",
    )


def test_epicentr_out_of_stock() -> None:
    result = EpicentrParser().parse_html(load_html("epicentr_out_of_stock.html"))

    assert result.title == GLUE
    assert result.is_available is False
    assert result.price == Decimal("749.00")
    assert result.old_price is None


def test_epicentr_prefers_main_product_over_other_product_blocks() -> None:
    other = (
        '<div itemscope itemtype="https://schema.org/Product"><h1 itemprop="name">Інший</h1>'
        '<div data-product-price-main><data itemprop="price" content="1.00"></data></div></div>'
    )
    html = load_html("epicentr_product.html").replace('<div id="main">', other + '<div id="main">')

    assert EpicentrParser().parse_html(html).title == GLUE


def test_generic_parser_handles_graph_aggregate_offer_and_image_object() -> None:
    result = SchemaOrgParser().parse_html(load_html("generic_graph.html"))

    assert result == ParseResult(
        title="Навушники Example Buds",
        price=Decimal("1299.00"),
        currency="UAH",
        is_available=True,
        sku="12345",
        image_url="https://shop.example.com/buds.jpg",
    )


@pytest.mark.parametrize("parser_cls", [SchemaOrgParser, PromParser, EpicentrParser])
def test_page_without_product_raises_parse_error(parser_cls: type) -> None:
    with pytest.raises(ParseError) as error:
        parser_cls().parse_html(load_html("no_product.html"), url="https://x/cat")

    assert error.value.retryable is False


def test_json_ld_product_without_name_raises_parse_error() -> None:
    html = (
        '<script type="application/ld+json">{"@type": "Product", "offers": {"price": 1}}</script>'
    )

    with pytest.raises(ParseError, match="no name"):
        SchemaOrgParser().parse_html(html)
