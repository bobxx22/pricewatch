from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.catalog import services
from scraping import ScrapingError
from scraping.listings import ListingItem


class Command(BaseCommand):
    help = (
        "List the products of a category page, cheapest first, and optionally track them. "
        "Rozetka categories are read over HTTP; listings with a JavaScript 'load more' button "
        "(the webscraper.io test shop) use a headless browser."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("url", metavar="URL")
        parser.add_argument(
            "--pages", type=int, default=1, help="Pages or 'load more' batches (default: 1)."
        )
        parser.add_argument("--max-price", type=Decimal, help="Only products up to this price.")
        parser.add_argument("--limit", type=int, default=20, help="Rows to show (default: 20).")
        parser.add_argument(
            "--track", action="store_true", help="Start tracking the products that are shown."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["pages"] < 1 or options["limit"] < 1:
            raise CommandError("--pages and --limit must be at least 1.")
        try:
            items = services.scan_category(options["url"], pages=options["pages"])
        except (ValueError, ScrapingError) as exc:
            raise CommandError(str(exc)) from exc

        if options["max_price"] is not None:
            items = [i for i in items if i.price is not None and i.price <= options["max_price"]]
        items.sort(key=lambda i: (i.price is None, i.price or 0))
        shown = items[: options["limit"]]
        self.stdout.write(f"Found {len(items)} products, showing {len(shown)}:")
        for item in shown:
            self.stdout.write(_row(item))

        if options["track"]:
            created = sum(services.add_product(item.url)[1] for item in shown)
            self.stdout.write(
                self.style.SUCCESS(f"Tracking {len(shown)} products ({created} new).")
            )


def _row(item: ListingItem) -> str:
    price = f"{item.price} {item.currency}" if item.price is not None else "no price"
    old = f" (was {item.old_price})" if item.old_price is not None else ""
    return f"{price:>16}{old:<18} {item.title[:70]}\n{'':16} {item.url}"
