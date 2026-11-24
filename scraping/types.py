"""Data types and errors shared by all parsers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Normalized product data extracted from a shop page."""

    title: str
    price: Decimal | None
    currency: str = "UAH"
    is_available: bool | None = None
    old_price: Decimal | None = None
    sku: str = ""
    image_url: str = ""

    def __post_init__(self) -> None:
        # An "old price" only means something when it is higher than the current one.
        if self.old_price is not None and (self.price is None or self.old_price <= self.price):
            object.__setattr__(self, "old_price", None)


class ScrapingError(Exception):
    """Base error. `retryable` tells the caller whether trying again later can help."""

    retryable = False

    def __init__(self, message: str, *, retryable: bool | None = None) -> None:
        super().__init__(message)
        if retryable is not None:
            self.retryable = retryable


class FetchError(ScrapingError):
    """Network failure or an unexpected HTTP status."""

    retryable = True


class RobotsDisallowedError(ScrapingError):
    """The shop's robots.txt does not allow fetching this URL."""


class ParseError(ScrapingError):
    """The page was fetched, but the product data was not found in it."""
