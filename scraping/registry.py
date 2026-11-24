"""Maps shop domains to parser classes."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from scraping.base import BaseParser
    from scraping.fetchers import Fetcher

_PARSERS: dict[str, type[BaseParser]] = {}


def normalize_domain(host: str) -> str:
    return host.strip().lower().rstrip(".").removeprefix("www.")


def domain_from_url(url: str) -> str:
    host = urlsplit(url).hostname
    if not host:
        raise ValueError(f"Not an absolute URL: {url!r}")
    return normalize_domain(host)


def register[P: type[BaseParser]](parser_cls: P) -> P:
    """Class decorator that makes a parser handle its `domains`."""
    if not parser_cls.domains:
        raise ValueError(f"{parser_cls.__name__} must define `domains`")
    for raw_domain in parser_cls.domains:
        domain = normalize_domain(raw_domain)
        existing = _PARSERS.get(domain)
        if existing is not None and existing is not parser_cls:
            raise ValueError(f"{domain} is already handled by {existing.__name__}")
        _PARSERS[domain] = parser_cls
    return parser_cls


def resolve(url: str) -> tuple[str, type[BaseParser]]:
    """Return (shop domain, parser class) for a URL.

    Subdomains use their parent's parser (m.prom.ua -> prom.ua). Unknown shops get
    the generic JSON-LD parser and their own hostname as the shop domain.
    """
    host = domain_from_url(url)
    labels = host.split(".")
    for start in range(len(labels) - 1):
        candidate = ".".join(labels[start:])
        if candidate in _PARSERS:
            return candidate, _PARSERS[candidate]

    from scraping.parsers.generic import SchemaOrgParser

    return host, SchemaOrgParser


def get_parser(url: str, fetcher: Fetcher | None = None) -> BaseParser:
    _, parser_cls = resolve(url)
    return parser_cls(fetcher=fetcher)


def registered_domains() -> dict[str, str]:
    return {domain: cls.__name__ for domain, cls in sorted(_PARSERS.items())}
