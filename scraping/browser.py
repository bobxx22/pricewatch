"""Headless-browser fetcher (Playwright) for pages that only fill in with JavaScript.

One instance owns one browser. Playwright's sync objects are bound to the thread that
created them, so keep an instance inside one thread and close it when done
(it is a context manager).
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from types import TracebackType
from typing import Self

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Route,
    sync_playwright,
)
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from scraping.fetchers import DEFAULT_USER_AGENT, HttpFetcher, check_status
from scraping.types import FetchError, RobotsDisallowedError

logger = logging.getLogger(__name__)

# A scraper never needs these; skipping them makes heavy pages load much faster.
BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font"})
SETTLE_TIMEOUT_MS = 10_000

PageAction = Callable[[Page], None]


class PlaywrightFetcher:
    """Renders a page in headless Chromium and returns the resulting DOM as HTML.

    robots.txt is checked over plain HTTP first, so a disallowed page never opens.
    `channel="chrome"` uses the installed Google Chrome instead of Playwright's own build.
    """

    def __init__(
        self,
        *,
        user_agent: str = "",
        timeout: float = 30.0,
        respect_robots_txt: bool = True,
        channel: str = "",
        headless: bool = True,
        block_resources: bool = True,
        robots_fetcher: HttpFetcher | None = None,
    ) -> None:
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.timeout_ms = timeout * 1000
        self.respect_robots_txt = respect_robots_txt
        self.channel = channel or None
        self.headless = headless
        self.block_resources = block_resources
        self._robots = robots_fetcher or HttpFetcher(user_agent=self.user_agent, timeout=timeout)
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    def get(
        self, url: str, *, wait_for: str | None = None, actions: PageAction | None = None
    ) -> str:
        """Open `url`, wait for `wait_for` (a CSS selector) or for the network to go quiet,
        run `actions` (clicks, scrolling) and return the page's HTML."""
        if self.respect_robots_txt and not self._robots.robots_allows(url):
            raise RobotsDisallowedError(f"robots.txt disallows {url}")
        page = self._context_or_start().new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            if response is None:
                raise FetchError(f"No response from {url}")
            check_status(response.status, url)
            if wait_for:
                # "attached", not "visible": data such as JSON-LD scripts is never visible.
                page.wait_for_selector(wait_for, state="attached", timeout=self.timeout_ms)
            else:
                self._settle(page)
            if actions is not None:
                actions(page)
            return page.content()
        except PlaywrightError as exc:
            raise FetchError(f"Browser error on {url}: {_first_line(exc)}") from exc
        finally:
            page.close()

    def close(self) -> None:
        for resource in (self._context, self._browser):
            if resource is not None:
                try:
                    resource.close()
                except PlaywrightError:
                    logger.debug("Browser resource was already closed", exc_info=True)
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = self._browser = self._context = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _context_or_start(self) -> BrowserContext:
        if self._context is not None:
            return self._context
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(
                channel=self.channel, headless=self.headless
            )
        except PlaywrightError as exc:
            self.close()
            raise FetchError(
                f"Could not start the browser ({_first_line(exc)}). Run "
                "`uv run playwright install chromium` or set PLAYWRIGHT_CHANNEL=chrome.",
                retryable=False,
            ) from exc
        self._context = self._browser.new_context(
            user_agent=self.user_agent, locale="uk-UA", viewport={"width": 1366, "height": 900}
        )
        if self.block_resources:
            self._context.route("**/*", _skip_heavy_resources)
        return self._context

    @staticmethod
    def _settle(page: Page) -> None:
        # Pages with analytics or long polling never go fully idle; the DOM is ready anyway.
        with contextlib.suppress(PlaywrightTimeoutError):
            page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)


def _skip_heavy_resources(route: Route) -> None:
    if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
        route.abort()
    else:
        route.continue_()


def _first_line(exc: Exception) -> str:
    return (str(exc).strip().splitlines() or [type(exc).__name__])[0]
