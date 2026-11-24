"""Generic parser for any shop that publishes schema.org Product data (JSON-LD or microdata)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from bs4 import SoupStrainer, Tag

from scraping.base import BaseParser
from scraping.extract import (
    clean_text,
    find_json_ld_product,
    find_microdata_product,
    first_image,
    first_offer,
    microdata_value,
    own_property,
    parse_availability,
    parse_price,
    strikethrough_price,
)
from scraping.types import ParseError, ParseResult

# Build only the JSON-LD <script> tags into the tree: about 2x faster on a 300 KB page.
JSON_LD_ONLY = SoupStrainer("script", attrs={"type": "application/ld+json"})


class SchemaOrgParser(BaseParser):
    """Fallback for shops without a dedicated parser, and a base for schema.org shops.

    Reads JSON-LD first (Product and ProductGroup variants, offer lists, AggregateOffer,
    the pre-discount price in priceSpecification), then microdata.
    """

    def parse_html(self, html: str, *, url: str = "") -> ParseResult:
        product = find_json_ld_product(self.make_soup(html, parse_only=JSON_LD_ONLY), url)
        if product is not None:
            return self.result_from_json_ld(product)
        scope = find_microdata_product(self.make_soup(html))
        if scope is not None:
            return self.result_from_microdata(scope, url=url)
        raise ParseError(f"No schema.org Product (JSON-LD or microdata): {url or 'page'}")

    def result_from_json_ld(self, product: dict[str, Any]) -> ParseResult:
        title = clean_text(product.get("name"))
        if not title:
            raise ParseError("Product JSON-LD has no name")
        offer = first_offer(product)
        return ParseResult(
            title=title,
            price=parse_price(offer.get("price") or offer.get("lowPrice")),
            currency=clean_text(offer.get("priceCurrency")).upper() or "UAH",
            is_available=parse_availability(offer.get("availability")),
            old_price=parse_price(strikethrough_price(offer)),
            sku=clean_text(product.get("sku")),
            image_url=first_image(product.get("image")),
        )

    def result_from_microdata(self, scope: Tag, *, url: str = "") -> ParseResult:
        title = microdata_value(own_property(scope, "name"))
        if not title:
            raise ParseError("Product microdata has no name")
        offer = own_property(scope, "offers") or scope
        image = microdata_value(own_property(scope, "image"))
        return ParseResult(
            title=title,
            price=parse_price(microdata_value(own_property(offer, "price"))),
            currency=microdata_value(own_property(offer, "priceCurrency")).upper() or "UAH",
            is_available=parse_availability(microdata_value(own_property(offer, "availability"))),
            sku=microdata_value(own_property(scope, "sku")),
            image_url=urljoin(url, image) if image else "",
        )
