"""webscraper.io e-commerce test site: a public shop built for practising scraping.

Its "more" catalog renders every product card with JavaScript and grows only through a
"More" button, so its listings are read with a headless browser. Product pages are
server-rendered schema.org microdata, so tracking prices needs nothing special.
"""

from __future__ import annotations

from scraping.listings import ListingSpec, register_listing
from scraping.parsers.generic import SchemaOrgParser
from scraping.registry import register


@register
class WebScraperTestShopParser(SchemaOrgParser):
    shop_name = "WebScraper.io test shop"
    domains = ("webscraper.io",)


register_listing(
    "webscraper.io",
    ListingSpec(
        tile=".thumbnail",
        link="a.title",
        price=".price",
        image="img",
        currency="USD",
        load_more="a.ecomerce-items-scroll-more",
    ),
)
