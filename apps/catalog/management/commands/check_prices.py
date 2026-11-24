from __future__ import annotations

import time
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from apps.catalog import services
from apps.catalog.management.commands._output import format_outcome
from apps.catalog.models import Product
from scraping.registry import normalize_domain


class Command(BaseCommand):
    help = "Check prices right now, without Celery. By default only products that are due."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--all", action="store_true", help="Check every active product, not only due ones."
        )
        parser.add_argument(
            "--product", type=int, action="append", dest="product_ids", metavar="ID"
        )
        parser.add_argument("--shop", metavar="DOMAIN", help="Only products of this shop.")
        parser.add_argument(
            "--delay",
            type=float,
            help="Seconds between requests (default: SCRAPER_DELAY_SECONDS).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        products = Product.objects.select_related("shop")
        if options["product_ids"]:
            products = products.filter(pk__in=options["product_ids"])
        elif options["all"]:
            products = products.filter(is_active=True, shop__is_active=True)
        else:
            products = products.due_for_check()
        if options["shop"]:
            products = products.filter(shop__domain=normalize_domain(options["shop"]))

        products = list(products.order_by("pk"))
        if not products:
            self.stdout.write("Nothing to check.")
            return

        delay = settings.SCRAPER_DELAY if options["delay"] is None else options["delay"]
        fetcher = services.build_fetcher()  # one HTTP session for the whole run
        failed = 0
        for index, product in enumerate(products):
            if index and delay > 0:
                time.sleep(delay)
            outcome = services.check_product(product, fetcher=fetcher)
            failed += not outcome.ok
            self.stdout.write(format_outcome(product, outcome))

        summary = f"Checked {len(products)}, failed {failed}."
        self.stdout.write(self.style.WARNING(summary) if failed else self.style.SUCCESS(summary))
