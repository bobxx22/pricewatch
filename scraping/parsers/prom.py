"""Prom.ua: product data comes from JSON-LD, the pre-discount price only from the markup."""

from __future__ import annotations

from dataclasses import replace

from bs4 import SoupStrainer

from scraping.extract import parse_price
from scraping.parsers.generic import SchemaOrgParser
from scraping.registry import register
from scraping.types import ParseResult

OLD_PRICE_ONLY = SoupStrainer(attrs={"data-qaid": "old_price"})


@register
class PromParser(SchemaOrgParser):
    shop_name = "Prom.ua"
    domains = ("prom.ua",)

    def parse_html(self, html: str, *, url: str = "") -> ParseResult:
        result = super().parse_html(html, url=url)
        old_price_tag = self.make_soup(html, parse_only=OLD_PRICE_ONLY).find(
            attrs={"data-qaprice": True}
        )
        if old_price_tag is None:
            return result
        return replace(result, old_price=parse_price(old_price_tag["data-qaprice"]))
