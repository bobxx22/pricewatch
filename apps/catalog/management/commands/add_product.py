from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.catalog import services
from apps.catalog.management.commands._output import format_outcome


class Command(BaseCommand):
    help = "Start tracking one or more product URLs."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("urls", nargs="+", metavar="URL")
        parser.add_argument("--check", action="store_true", help="Check the price right away.")

    def handle(self, *args: Any, urls: list[str], check: bool, **options: Any) -> None:
        invalid = 0
        fetcher = services.build_fetcher() if check else None
        for raw_url in urls:
            try:
                product, created = services.add_product(raw_url)
            except ValueError as exc:
                invalid += 1
                self.stderr.write(self.style.ERROR(str(exc)))
                continue
            status = "Added" if created else "Already tracked"
            self.stdout.write(f"{status}: #{product.pk} {product.url} ({product.shop.name})")
            if check:
                self.stdout.write(
                    format_outcome(product, services.check_product(product, fetcher=fetcher))
                )
        if invalid:
            raise CommandError(f"{invalid} of {len(urls)} URLs were not added.")
