"""Canaries against the real shops: they fail when a shop changes its markup.

Skipped by default; run with `uv run pytest -m live`. The browser case also needs
Chromium (or PLAYWRIGHT_CHANNEL=chrome).
"""

import os

import pytest
from django.conf import settings

from scraping import HttpFetcher, get_parser
from scraping.browser import PlaywrightFetcher
from scraping.listings import scan_listing
from tests.helpers import (
    EPICENTR_URL,
    PROM_URL,
    ROZETKA_CATEGORY_URL,
    ROZETKA_URL,
    WEBSCRAPER_LISTING_URL,
    WEBSCRAPER_PRODUCT_URL,
)

pytestmark = pytest.mark.live


@pytest.mark.parametrize("url", [PROM_URL, EPICENTR_URL, ROZETKA_URL, WEBSCRAPER_PRODUCT_URL])
def test_real_product_page_still_parses(url: str) -> None:
    result = get_parser(url, fetcher=HttpFetcher()).parse(url)

    assert result.title
    assert result.price is not None
    assert result.price > 0


def test_rozetka_category_pages_over_http() -> None:
    items = scan_listing(ROZETKA_CATEGORY_URL, pages=2, http=HttpFetcher(), delay=1)

    assert len(items) > 60
    assert all(item.url.startswith("https://rozetka.com.ua/") for item in items)


@pytest.mark.browser
def test_load_more_listing_in_a_real_browser() -> None:
    channel = os.environ.get("PLAYWRIGHT_CHANNEL", settings.PLAYWRIGHT_CHANNEL)
    with PlaywrightFetcher(channel=channel) as browser:
        items = scan_listing(WEBSCRAPER_LISTING_URL, pages=2, http=HttpFetcher(), browser=browser)

    assert len(items) == 12
