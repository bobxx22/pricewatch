"""Epicentr K: no JSON-LD, so the parser reads schema.org microdata and data-* attributes.

CSS classes on this site are generated hashes (e.g. `_Al-5uY1o`) that change with
frontend releases, so the selectors deliberately never use them.
"""

from __future__ import annotations

from bs4 import Tag

from scraping.base import BaseParser
from scraping.extract import clean_text, parse_availability, parse_price
from scraping.registry import register
from scraping.types import ParseError, ParseResult

PRODUCT = '[itemtype$="schema.org/Product"]'
MAIN_PRODUCT = f'[itemprop="mainEntity"]{PRODUCT}'


@register
class EpicentrParser(BaseParser):
    shop_name = "Epicentr K"
    domains = ("epicentrk.ua",)

    def parse_html(self, html: str, *, url: str = "") -> ParseResult:
        soup = self.make_soup(html)
        product = soup.select_one(MAIN_PRODUCT) or soup.select_one(PRODUCT)
        if product is None:
            raise ParseError(f"No schema.org Product microdata: {url or 'page'}")

        title = clean_text(_text(product.select_one('h1[itemprop="name"]')))
        if not title:
            raise ParseError(f"Product title not found: {url or 'page'}")

        # The page renders the main price block twice; only the first carries microdata.
        price = product.select_one('[data-product-price-main] [itemprop="price"]')
        currency = product.select_one('[data-product-price-main] [itemprop="priceCurrency"]')
        old_price = product.select_one('[data-product-price-old] [itemprop="price"]')
        availability = product.select_one('[itemprop="offers"] link[itemprop="availability"]')
        image = soup.select_one('meta[property="og:image"]')

        return ParseResult(
            title=title,
            price=parse_price(_attr(price, "content")),
            currency=_attr(currency, "content").upper() or "UAH",
            is_available=parse_availability(_attr(availability, "href")),
            old_price=parse_price(_attr(old_price, "content")),
            sku=clean_text(_text(product.select_one('[itemprop="sku"]'))),
            image_url=_attr(image, "content"),
        )


def _attr(tag: Tag | None, name: str) -> str:
    value = tag.get(name) if tag is not None else None
    return value.strip() if isinstance(value, str) else ""


def _text(tag: Tag | None) -> str:
    return tag.get_text(" ", strip=True) if tag is not None else ""
