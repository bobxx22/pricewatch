"""Base class for shop parsers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from bs4 import BeautifulSoup, SoupStrainer

from scraping.fetchers import Fetcher, HttpFetcher
from scraping.types import ParseResult


class BaseParser(ABC):
    """One subclass per shop: set `domains`, implement `parse_html`, decorate with @register.

    Fetching and parsing are separate steps, so parsers are tested on saved HTML
    without touching the network.
    """

    shop_name: ClassVar[str] = ""
    domains: ClassVar[tuple[str, ...]] = ()

    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or HttpFetcher()

    def parse(self, url: str) -> ParseResult:
        return self.parse_html(self.fetcher.get(url), url=url)

    @abstractmethod
    def parse_html(self, html: str, *, url: str = "") -> ParseResult:
        """Extract product data from page HTML. Raise ParseError when it is not there."""

    @staticmethod
    def make_soup(html: str, parse_only: SoupStrainer | None = None) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml", parse_only=parse_only)
