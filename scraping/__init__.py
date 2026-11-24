"""Shop scrapers. Framework-free: no Django imports anywhere in this package."""

from scraping import parsers  # noqa: F401  (registers the built-in parsers)
from scraping.base import BaseParser
from scraping.fetchers import Fetcher, HttpFetcher
from scraping.registry import domain_from_url, get_parser, register, registered_domains, resolve
from scraping.types import (
    FetchError,
    ParseError,
    ParseResult,
    RobotsDisallowedError,
    ScrapingError,
)

__all__ = [
    "BaseParser",
    "FetchError",
    "Fetcher",
    "HttpFetcher",
    "ParseError",
    "ParseResult",
    "RobotsDisallowedError",
    "ScrapingError",
    "domain_from_url",
    "get_parser",
    "register",
    "registered_domains",
    "resolve",
]
