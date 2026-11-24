"""Category and listing pages: collect product cards (title, URL, price) from a catalog.

Two kinds of listings exist in the wild, and each gets the cheaper tool that works:

* server-rendered pages with URL pagination (Rozetka `.../page=2/`): plain HTTP;
* listings that grow only through a JavaScript "load more" button: a headless browser
  that clicks it (PlaywrightFetcher).
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from scraping.browser import PlaywrightFetcher
from scraping.extract import clean_text, parse_price
from scraping.fetchers import Fetcher
from scraping.registry import domain_from_url

MORE_ITEMS_TIMEOUT_MS = 15_000


@dataclass(frozen=True, slots=True)
class ListingItem:
    """One product card from a listing page."""

    title: str
    url: str
    price: Decimal | None
    old_price: Decimal | None = None
    currency: str = "UAH"
    image_url: str = ""

    def __post_init__(self) -> None:
        if self.old_price is not None and (self.price is None or self.old_price <= self.price):
            object.__setattr__(self, "old_price", None)


@dataclass(frozen=True)
class ListingSpec:
    """CSS selectors of a shop's product cards and how to get the next batch of them."""

    tile: str
    link: str  # <a> inside a card: its href is the product URL, its title or text the name
    price: str
    old_price: str | None = None
    image: str | None = None
    currency: str = "UAH"
    page_url: Callable[[str, int], str] | None = None  # URL of page n >= 2 (server pagination)
    load_more: str | None = None  # a JavaScript "load more" button: requires a browser

    @property
    def needs_browser(self) -> bool:
        return self.load_more is not None


_LISTINGS: dict[str, ListingSpec] = {}


def register_listing(domain: str, spec: ListingSpec) -> None:
    _LISTINGS[domain] = spec


def listing_spec_for(url: str) -> ListingSpec:
    host = domain_from_url(url)
    labels = host.split(".")
    for start in range(len(labels) - 1):
        spec = _LISTINGS.get(".".join(labels[start:]))
        if spec is not None:
            return spec
    supported = ", ".join(sorted(_LISTINGS)) or "none"
    raise ValueError(f"Listing pages of {host} are not supported (supported: {supported})")


def scan_listing(
    url: str,
    *,
    pages: int = 1,
    http: Fetcher,
    browser: PlaywrightFetcher | None = None,
    delay: float = 0.0,
) -> list[ListingItem]:
    """Product cards from the first `pages` pages (or "load more" batches) of a listing."""
    spec = listing_spec_for(url)
    if spec.needs_browser:
        if browser is None:
            raise ValueError(f"{domain_from_url(url)} listings need a browser fetcher")
        html = browser.get(
            url, wait_for=spec.tile, actions=lambda page: click_load_more(page, spec, pages - 1)
        )
        return parse_listing(html, spec, url)

    items = parse_listing(http.get(url), spec, url)
    if spec.page_url is not None:
        for number in range(2, pages + 1):
            if delay > 0:
                time.sleep(delay)
            page_items = parse_listing(http.get(spec.page_url(url, number)), spec, url)
            if not page_items:
                break
            items.extend(page_items)
    return _unique(items)


def click_load_more(page: Page, spec: ListingSpec, times: int) -> None:
    """Click the "load more" button up to `times` times, waiting for new cards each time."""
    if spec.load_more is None:
        return
    for _ in range(max(times, 0)):
        button = page.locator(spec.load_more).first
        if not button.is_visible():
            return  # everything is loaded
        before = page.locator(spec.tile).count()
        button.click()
        try:
            page.wait_for_function(
                "([selector, count]) => document.querySelectorAll(selector).length > count",
                arg=[spec.tile, before],
                timeout=MORE_ITEMS_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError:
            return


def parse_listing(html: str, spec: ListingSpec, base_url: str) -> list[ListingItem]:
    soup = BeautifulSoup(html, "lxml")
    items = []
    for card in soup.select(spec.tile):
        link = card.select_one(spec.link)
        href = link.get("href") if link is not None else None
        if not isinstance(href, str) or not href.strip():
            continue
        # Card links often show a shortened name; the title attribute keeps the full one.
        title = clean_text(link.get("title")) or clean_text(link.get_text(" ", strip=True))
        image = card.select_one(spec.image) if spec.image else None
        image_src = image.get("src") if image is not None else None
        items.append(
            ListingItem(
                title=title,
                url=urljoin(base_url, href.strip()),
                price=parse_price(_text(card, spec.price)),
                old_price=parse_price(_text(card, spec.old_price)),
                currency=spec.currency,
                image_url=urljoin(base_url, image_src) if isinstance(image_src, str) else "",
            )
        )
    return _unique(items)


def _text(card: BeautifulSoup, selector: str | None) -> str | None:
    element = card.select_one(selector) if selector else None
    return element.get_text(" ", strip=True) if element is not None else None


def _unique(items: list[ListingItem]) -> list[ListingItem]:
    """Drop repeated products, keeping the first occurrence and the page order."""
    first: dict[str, ListingItem] = {}
    for item in items:
        first.setdefault(item.url, item)
    return list(first.values())


def rozetka_page_url(url: str, number: int) -> str:
    """Rozetka paginates with a path segment: .../c80003/page=2/."""
    base = re.sub(r"page=[\d,]+/?$", "", url.split("?", 1)[0].rstrip("/") + "/")
    return f"{base}page={number}/"
