"""PlaywrightFetcher against a local HTTP server, in a real headless Chromium.

Locally these run when a browser is available (`uv run playwright install chromium` or
PLAYWRIGHT_CHANNEL=chrome); CI installs Chromium and sets REQUIRE_BROWSER=1.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from django.conf import settings

from scraping import FetchError, RobotsDisallowedError
from scraping.browser import PlaywrightFetcher
from scraping.listings import _LISTINGS, ListingSpec, register_listing, scan_listing
from scraping.parsers.generic import SchemaOrgParser

pytestmark = pytest.mark.browser

JS_PRODUCT = """<!DOCTYPE html><html><head><title>JS shop</title></head><body>
<div id="app">Завантаження…</div>
<script>
  setTimeout(() => {
    const data = document.createElement("script");
    data.type = "application/ld+json";
    data.textContent = JSON.stringify({"@type": "Product", "name": "Чайник Philips HD9350",
      "offers": {"price": "1499", "priceCurrency": "UAH",
                 "availability": "https://schema.org/InStock"}});
    document.head.append(data);
    document.getElementById("app").textContent = "Чайник Philips HD9350 — 1499 ₴";
  }, 150);
</script></body></html>"""

LOAD_MORE = """<!DOCTYPE html><html><body>
<div id="cards"></div>
<button class="more" type="button">Показати ще</button>
<script>
  let shown = 0;
  function addCards() {
    for (let i = 0; i < 3; i += 1) {
      shown += 1;
      document.getElementById("cards").insertAdjacentHTML("beforeend",
        `<div class="card"><a class="name" href="/item/${shown}">Товар ${shown}</a>` +
        `<span class="cost">${100 * shown} ₴</span></div>`);
    }
    if (shown >= 9) document.querySelector(".more").remove();
  }
  addCards();
  document.querySelector(".more").addEventListener("click", () => setTimeout(addCards, 100));
</script></body></html>"""

PAGES = {"/js-product": (200, JS_PRODUCT), "/listing": (200, LOAD_MORE)}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        status, body = PAGES.get(self.path, (404, "<h1>Немає такої сторінки</h1>"))
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass


class _Robots:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.checked: list[str] = []

    def robots_allows(self, url: str) -> bool:
        self.checked.append(url)
        return self.allow


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser() -> Iterator[PlaywrightFetcher]:
    channel = os.environ.get("PLAYWRIGHT_CHANNEL", settings.PLAYWRIGHT_CHANNEL)
    fetcher = PlaywrightFetcher(channel=channel, timeout=15, robots_fetcher=_Robots())
    try:
        fetcher._context_or_start()  # launch now, so a missing browser skips the module
    except FetchError as exc:
        fetcher.close()
        if os.environ.get("REQUIRE_BROWSER"):
            raise
        pytest.skip(f"No headless browser here: {exc}")
    yield fetcher
    fetcher.close()


def test_content_rendered_by_javascript_is_captured(
    browser: PlaywrightFetcher, server: str
) -> None:
    html = browser.get(f"{server}/js-product", wait_for='script[type="application/ld+json"]')

    result = SchemaOrgParser().parse_html(html)
    assert (result.title, result.price, result.is_available) == (
        "Чайник Philips HD9350",
        Decimal("1499.00"),
        True,
    )


def test_load_more_button_is_clicked_until_enough_cards(
    browser: PlaywrightFetcher, server: str
) -> None:
    register_listing(
        "127.0.0.1",
        ListingSpec(tile=".card", link="a.name", price=".cost", load_more="button.more"),
    )
    try:
        items = scan_listing(f"{server}/listing", pages=2, http=None, browser=browser)  # type: ignore[arg-type]
        everything = scan_listing(f"{server}/listing", pages=10, http=None, browser=browser)  # type: ignore[arg-type]
    finally:
        _LISTINGS.pop("127.0.0.1", None)

    assert [item.title for item in items] == [f"Товар {n}" for n in range(1, 7)]
    assert items[-1].price == Decimal("600.00")
    assert len(everything) == 9  # stops when the button disappears


def test_http_errors_keep_their_meaning(browser: PlaywrightFetcher, server: str) -> None:
    with pytest.raises(FetchError, match="404") as error:
        browser.get(f"{server}/missing")

    assert error.value.retryable is False


def test_robots_txt_is_checked_before_the_page_opens(server: str) -> None:
    robots = _Robots(allow=False)
    fetcher = PlaywrightFetcher(robots_fetcher=robots)

    with pytest.raises(RobotsDisallowedError):
        fetcher.get(f"{server}/js-product")

    assert robots.checked == [f"{server}/js-product"]
    assert fetcher._browser is None  # the browser was never started
