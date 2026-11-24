"""Rozetka.

Product pages publish a schema.org ProductGroup with variants, which SchemaOrgParser reads.
Category pages are server-rendered, 60 tiles per `.../page=N/` URL, so listings are read
over plain HTTP. (The "Показати ще" button switches to `page=1,2/`, a URL robots.txt
disallows, so it is deliberately not used.)
"""

from __future__ import annotations

from scraping.listings import ListingSpec, register_listing, rozetka_page_url
from scraping.parsers.generic import SchemaOrgParser
from scraping.registry import register


@register
class RozetkaParser(SchemaOrgParser):
    shop_name = "Rozetka"
    domains = ("rozetka.com.ua",)


register_listing(
    "rozetka.com.ua",
    ListingSpec(
        tile="rz-product-tile",
        link="a.tile-title",
        price="rz-tile-price .price",
        old_price="rz-tile-price .old-price",
        image="img.tile-image",
        page_url=rozetka_page_url,
    ),
)
