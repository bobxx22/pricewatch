import pytest

from scraping import BaseParser, ParseResult, get_parser, register, resolve
from scraping.parsers.epicentr import EpicentrParser
from scraping.parsers.generic import SchemaOrgParser
from scraping.parsers.prom import PromParser
from tests.helpers import PROM_URL, FakeFetcher


@pytest.mark.parametrize(
    ("url", "domain", "parser_cls"),
    [
        ("https://prom.ua/ua/p1-x.html", "prom.ua", PromParser),
        ("https://www.prom.ua/p1-x.html", "prom.ua", PromParser),
        ("https://m.prom.ua/p1-x.html", "prom.ua", PromParser),
        ("https://EPICENTRK.UA/ua/shop/x.html", "epicentrk.ua", EpicentrParser),
        ("https://www.shop.example.com/item/1", "shop.example.com", SchemaOrgParser),
        # A suffix match must respect domain labels: notprom.ua is not prom.ua.
        ("https://notprom.ua/p1.html", "notprom.ua", SchemaOrgParser),
    ],
)
def test_resolve(url: str, domain: str, parser_cls: type[BaseParser]) -> None:
    assert resolve(url) == (domain, parser_cls)


def test_resolve_rejects_relative_url() -> None:
    with pytest.raises(ValueError, match="absolute"):
        resolve("/ua/p1.html")


def test_get_parser_passes_fetcher_through() -> None:
    fetcher = FakeFetcher()
    parser = get_parser(PROM_URL, fetcher=fetcher)

    assert isinstance(parser, PromParser)
    assert parser.fetcher is fetcher


def test_register_requires_domains() -> None:
    class NoDomains(BaseParser):
        def parse_html(self, html: str, *, url: str = "") -> ParseResult:
            raise NotImplementedError

    with pytest.raises(ValueError, match="domains"):
        register(NoDomains)


def test_register_rejects_a_second_parser_for_a_domain() -> None:
    class AnotherProm(SchemaOrgParser):
        domains = ("www.prom.ua",)

    with pytest.raises(ValueError, match="already handled by PromParser"):
        register(AnotherProm)
    assert resolve(PROM_URL)[1] is PromParser
