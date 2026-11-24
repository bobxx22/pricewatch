"""HTTP layer: one place for headers, timeouts, retries and robots.txt."""

from __future__ import annotations

import logging
import threading
import time
from typing import Protocol
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scraping.types import FetchError, RobotsDisallowedError

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)
# Name matched against robots.txt groups. Unknown bots fall under "User-agent: *".
ROBOTS_AGENT = "PriceWatchBot"
ROBOTS_CACHE_SECONDS = 60 * 60


class Fetcher(Protocol):
    def get(self, url: str) -> str: ...


RETRYABLE_STATUSES = (429, 500, 502, 503, 504)


def check_status(status: int, url: str) -> None:
    """Turn an HTTP error status into a FetchError that says whether retrying can help."""
    if status in (404, 410):
        raise FetchError(f"Page not found (HTTP {status}): {url}", retryable=False)
    if status in (401, 403):
        raise FetchError(
            f"Access denied (HTTP {status}), the shop may block automated requests: {url}",
            retryable=False,
        )
    if status >= 400:
        raise FetchError(
            f"HTTP {status}: {url}", retryable=status in RETRYABLE_STATUSES or status >= 500
        )


class HttpFetcher:
    """Downloads pages with a shared session, retries with backoff and a robots.txt check."""

    retry_statuses = RETRYABLE_STATUSES

    def __init__(
        self,
        *,
        user_agent: str = "",
        timeout: float = 20.0,
        respect_robots_txt: bool = True,
        retries: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.respect_robots_txt = respect_robots_txt
        self.session = session or self._build_session(user_agent or DEFAULT_USER_AGENT, retries)

    @classmethod
    def _build_session(cls, user_agent: str, retries: int) -> requests.Session:
        retry = Retry(
            total=retries,
            backoff_factor=1.0,
            status_forcelist=cls.retry_statuses,
            allowed_methods=frozenset({"GET"}),
            # A long Retry-After would block the worker; Celery retries later instead.
            respect_retry_after_header=False,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session = requests.Session()
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
            }
        )
        return session

    def get(self, url: str) -> str:
        if self.respect_robots_txt and not self.robots_allows(url):
            raise RobotsDisallowedError(f"robots.txt disallows {url}")
        response = self._request(url)
        check_status(response.status_code, url)
        return _decoded_text(response)

    def robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        parser = _robots_cache.get(origin)
        if parser is None:
            parser = self._load_robots(origin)
            _robots_cache.put(origin, parser)
        return parser.can_fetch(ROBOTS_AGENT, url)

    def _load_robots(self, origin: str) -> RobotFileParser:
        parser = RobotFileParser(f"{origin}/robots.txt")
        response = self._request(parser.url)
        if response.status_code >= 500:
            # RFC 9309: an unreachable robots.txt means "assume disallowed for now".
            raise FetchError(f"robots.txt unavailable (HTTP {response.status_code}) for {origin}")
        if response.status_code >= 400:
            parser.allow_all = True  # RFC 9309: a missing robots.txt means no restrictions.
        else:
            parser.parse(_decoded_text(response).splitlines())
        return parser

    def _request(self, url: str) -> requests.Response:
        try:
            return self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise FetchError(f"Request failed: {url}: {exc}") from exc


def _decoded_text(response: requests.Response) -> str:
    # Without a charset in Content-Type, requests falls back to ISO-8859-1 and garbles Cyrillic.
    if "charset" not in response.headers.get("Content-Type", "").lower():
        response.encoding = "utf-8"
    return response.text


class _RobotsCache:
    """Process-wide cache, so every Celery task does not download robots.txt again."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._items: dict[str, tuple[float, RobotFileParser]] = {}
        self._lock = threading.Lock()

    def get(self, origin: str) -> RobotFileParser | None:
        with self._lock:
            item = self._items.get(origin)
        if item is None or time.monotonic() - item[0] > self._ttl:
            return None
        return item[1]

    def put(self, origin: str, parser: RobotFileParser) -> None:
        with self._lock:
            self._items[origin] = (time.monotonic(), parser)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_robots_cache = _RobotsCache(ROBOTS_CACHE_SECONDS)


def clear_robots_cache() -> None:
    _robots_cache.clear()
