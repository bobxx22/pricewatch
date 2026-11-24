"""Helpers that turn messy shop markup into clean values."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

_WHITESPACE = re.compile(r"[\s   ]+")
_NOT_NUMERIC = re.compile(r"[^\d.,\-]")
_CENTS = Decimal("0.01")

# schema.org/ItemAvailability values, lowercased.
_IN_STOCK = {"instock", "instoreonly", "onlineonly", "limitedavailability", "madetoorder"}
_OUT_OF_STOCK = {
    "outofstock",
    "soldout",
    "discontinued",
    "backorder",
    "preorder",
    "presale",
    "reserved",
}


def clean_text(value: Any) -> str:
    """Collapse whitespace, including non-breaking spaces, and strip the ends."""
    if value is None:
        return ""
    return _WHITESPACE.sub(" ", str(value)).strip()


def parse_price(value: Any) -> Decimal | None:
    """Parse 399, "719.20", "1 299,50 ₴" or "1,299.50" into a Decimal with two places.

    Returns None for empty, unparseable, zero and negative values.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        raw = str(value)
    else:
        raw = _NOT_NUMERIC.sub("", _WHITESPACE.sub("", str(value)))
        if "," in raw and "." in raw:
            # Whichever separator comes last is the decimal one: "1.299,50" / "1,299.50".
            thousands = "." if raw.rfind(",") > raw.rfind(".") else ","
            raw = raw.replace(thousands, "").replace(",", ".")
        elif "," in raw:
            head, _, tail = raw.rpartition(",")
            # "12,99" uses a decimal comma, "1,299" a thousands separator.
            raw = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else raw.replace(",", "")
        elif raw.count(".") > 1:
            raw = raw.replace(".", "")
    try:
        price = Decimal(raw)
    except InvalidOperation:
        return None
    if not price.is_finite() or price <= 0:
        return None
    return price.quantize(_CENTS)


def parse_availability(value: Any) -> bool | None:
    """Map a schema.org availability ("http://schema.org/InStock", "OutOfStock") to a bool."""
    if not value:
        return None
    token = str(value).strip().rstrip("/").rsplit("/", 1)[-1].lower()
    if token in _IN_STOCK:
        return True
    if token in _OUT_OF_STOCK:
        return False
    return None


def iter_json_ld(soup: BeautifulSoup) -> Iterator[dict[str, Any]]:
    """Yield every JSON-LD object on the page, unpacking lists, @graph and mainEntity."""
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            # strict=False tolerates raw control characters, which some shops leave in strings.
            data = json.loads(script.get_text(), strict=False)
        except json.JSONDecodeError:
            continue
        yield from _flatten(data)


def _flatten(data: Any) -> Iterator[dict[str, Any]]:
    if isinstance(data, list):
        for item in data:
            yield from _flatten(item)
    elif isinstance(data, dict):
        yield data
        for key in ("@graph", "mainEntity"):
            if isinstance(data.get(key), dict | list):
                yield from _flatten(data[key])


def has_type(obj: dict[str, Any], type_name: str) -> bool:
    types = obj.get("@type")
    return type_name in (types if isinstance(types, list) else [types])


def find_json_ld_product(soup: BeautifulSoup, url: str = "") -> dict[str, Any] | None:
    """The page's Product. For a ProductGroup (one model in several colours or sizes),
    the variant whose URL matches `url`, with the group's name and image as fallbacks."""
    for obj in iter_json_ld(soup):
        if has_type(obj, "Product"):
            return obj
        if has_type(obj, "ProductGroup") and (variant := _pick_variant(obj, url)):
            return variant
    return None


def _pick_variant(group: dict[str, Any], url: str) -> dict[str, Any] | None:
    # Other variants are often listed as bare {"url": ...}; only full entries are usable.
    variants = [
        v for v in as_list(group.get("hasVariant")) if isinstance(v, dict) and v.get("offers")
    ]
    if not variants:
        return None
    wanted = _url_key(url)
    variant = next((v for v in variants if wanted and _url_key(v.get("url")) == wanted), None)
    defaults = {key: group[key] for key in ("name", "image", "brand") if group.get(key)}
    return defaults | (variant or variants[0])


def _url_key(url: Any) -> str:
    if not isinstance(url, str) or not url:
        return ""
    parts = urlsplit(url)
    return f"{(parts.hostname or '').removeprefix('www.')}{parts.path.rstrip('/')}"


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def first_offer(product: dict[str, Any]) -> dict[str, Any]:
    """The product's offer: a single Offer, the first of a list, or an AggregateOffer."""
    offers = product.get("offers")
    if isinstance(offers, list):
        offers = next((offer for offer in offers if isinstance(offer, dict)), None)
    return offers if isinstance(offers, dict) else {}


def strikethrough_price(offer: dict[str, Any]) -> Any:
    """The pre-discount price, published as a schema.org StrikethroughPrice or ListPrice."""
    for spec in as_list(offer.get("priceSpecification")):
        if not isinstance(spec, dict):
            continue
        price_type = str(spec.get("priceType", "")).rstrip("/").rsplit("/", 1)[-1]
        if price_type in ("StrikethroughPrice", "ListPrice"):
            return spec.get("price")
    return None


def find_microdata_product(soup: BeautifulSoup) -> Tag | None:
    """The page's schema.org Product microdata scope, preferring the page's main entity."""
    return soup.select_one('[itemprop~="mainEntity"][itemtype$="schema.org/Product"]') or (
        soup.select_one('[itemscope][itemtype$="schema.org/Product"]')
    )


def own_property(scope: Tag | None, name: str) -> Tag | None:
    """First element carrying `itemprop=name` that belongs to `scope` itself,
    not to an item nested inside it (a brand's name is not the product's name)."""
    if scope is None:
        return None
    for element in scope.find_all(attrs={"itemprop": True}):
        if name in str(element.get("itemprop", "")).split() and _owner(element) is scope:
            return element
    return None


def _owner(element: Tag) -> Tag | None:
    return element.find_parent(attrs={"itemscope": True})


def microdata_value(element: Tag | None) -> str:
    """A microdata property's value, read the way the HTML spec defines it per element."""
    if element is None:
        return ""
    attribute = {
        "meta": "content",
        "a": "href",
        "link": "href",
        "img": "src",
        "source": "src",
        "data": "value",
        "meter": "value",
        "time": "datetime",
    }.get(element.name or "")
    if attribute is None and element.has_attr("content"):
        attribute = "content"  # widespread non-standard <span itemprop content="...">
    if attribute:
        value = element.get(attribute)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return clean_text(element.get_text(" ", strip=True))


def first_image(value: Any) -> str:
    """JSON-LD `image` can be a URL, a list of URLs or an ImageObject."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return next((url for url in map(first_image, value) if url), "")
    if isinstance(value, dict):
        return first_image(value.get("url") or value.get("contentUrl"))
    return ""
