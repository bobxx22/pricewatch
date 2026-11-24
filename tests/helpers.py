from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from apps.bot.telegram_api import TelegramApiError
from scraping import FetchError

FIXTURES = Path(__file__).parent / "fixtures" / "html"

PROM_URL = "https://prom.ua/ua/p2970749786-olivkovoe-maslo-monini.html"
EPICENTR_URL = "https://epicentrk.ua/ua/shop/kley-dlya-plitki-ceresit-sm-117-25kg.html"
ROZETKA_URL = "https://rozetka.com.ua/ua/samsung-sm-s931bzkgeuc/p525186024/"
ROZETKA_CATEGORY_URL = "https://rozetka.com.ua/ua/mobile-phones/c80003/"
WEBSCRAPER_PRODUCT_URL = "https://webscraper.io/test-sites/e-commerce/more/product/60"
WEBSCRAPER_LISTING_URL = "https://webscraper.io/test-sites/e-commerce/more/computers/laptops"


def load_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher:
    """Serves prepared pages instead of the network. A page can be HTML or an exception."""

    def __init__(self, pages: dict[str, str | Exception] | None = None) -> None:
        self.pages = dict(pages or {})
        self.requested: list[str] = []

    def get(self, url: str) -> str:
        self.requested.append(url)
        page = self.pages.get(url)
        if page is None:
            raise FetchError(f"No fake page for {url}", retryable=False)
        if isinstance(page, Exception):
            raise page
        return page


@dataclass
class FakeTelegram:
    """Stands in for TelegramClient: records messages, can fail for chosen chats."""

    sent: list[dict[str, Any]] = field(default_factory=list)
    failures: dict[int, TelegramApiError] = field(default_factory=dict)

    def send_message(self, chat_id: int, text: str, *, reply_markup: Any = None) -> None:
        if chat_id in self.failures:
            raise self.failures[chat_id]
        self.sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
