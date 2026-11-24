"""Demo data for a fresh checkout: a clearly marked demo shop with 60 days of price history.

The shop is inactive, so the scheduler never requests its made-up URLs, and the domain is
under .example (reserved, RFC 2606). `--clear` removes everything this command created.
"""

from __future__ import annotations

import random
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import PriceSnapshot, Product, Shop

DEMO_DOMAIN = "demo.pricewatch.example"
DEMO_PRODUCTS = (
    ("Навушники Sony WH-1000XM5 Black", 13999),
    ("Кавоварка De'Longhi Dedica Style EC685.M", 11299),
    ("Смартфон Samsung Galaxy A56 8/256GB Graphite", 17999),
    ("Робот-пилосос Xiaomi Robot Vacuum S20+ White", 15499),
    ("Ноутбук ASUS Vivobook 15 X1504VA-BQ1048", 23999),
    ("Електросамокат Segway Ninebot E2 Plus", 16999),
    ("Мультиварка Tefal Multicook & Stir RK905A34", 4299),
    ("Конструктор LEGO Technic 42171 Mercedes-AMG F1 W14", 8499),
)


class Command(BaseCommand):
    help = "Create (or with --clear remove) a demo shop with price history for screenshots."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--clear", action="store_true", help="Remove the demo data.")
        parser.add_argument("--seed", type=int, default=7, help="Random seed (default: 7).")

    @transaction.atomic
    def handle(self, *args: Any, clear: bool, seed: int, **options: Any) -> None:
        Product.objects.filter(shop__domain=DEMO_DOMAIN).delete()
        Shop.objects.filter(domain=DEMO_DOMAIN).delete()
        if clear:
            self.stdout.write("Demo data removed.")
            return

        shop = Shop.objects.create(name="Демо-магазин", domain=DEMO_DOMAIN, is_active=False)
        rng = random.Random(seed)
        now = timezone.now()
        for index, (title, base_price) in enumerate(DEMO_PRODUCTS, 1):
            product = Product.objects.create(
                shop=shop,
                url=f"https://{DEMO_DOMAIN}/p/{index}",
                title=title,
                sku=f"DEMO-{index:03}",
            )
            history = _history(rng, Decimal(base_price), now, drop_recently=index % 3 != 0)
            PriceSnapshot.objects.bulk_create(
                PriceSnapshot(
                    product=product, price=price, old_price=old, is_available=stock, recorded_at=at
                )
                for at, price, old, stock in history
            )
            _, price, old, stock = history[-1]
            checked = now - timedelta(minutes=rng.randint(3, 50))
            Product.objects.filter(pk=product.pk).update(
                price=price, old_price=old, is_available=stock, last_checked_at=checked
            )
        self.stdout.write(
            self.style.SUCCESS(f"Created {len(DEMO_PRODUCTS)} demo products in «{shop.name}».")
        )


def _history(rng: random.Random, base: Decimal, now, *, drop_recently: bool):
    """Step-wise price changes every few days, with sales and an occasional stock-out."""
    moment = now - timedelta(days=60)
    price = base
    rows = [(moment, price, None, True)]
    while True:
        moment += timedelta(days=rng.randint(3, 9), hours=rng.randint(0, 23))
        if moment > now - timedelta(days=8):
            break
        roll = rng.random()
        if roll < 0.12:
            rows.append((moment, price, None, False))  # sold out for a while
            continue
        change = Decimal(rng.choice([-12, -8, -5, -3, 3, 4, 6, 9])) / 100
        price = _round(base * (1 + change) if rng.random() < 0.5 else price * (1 + change))
        old = base if price < base * Decimal("0.95") else None
        rows.append((moment, price, old, True))
    if drop_recently:
        moment = now - timedelta(days=rng.randint(1, 5), hours=rng.randint(1, 20))
        price = _round(price * (1 - Decimal(rng.choice([8, 12, 15, 22])) / 100))
        rows.append((moment, price, base if price < base else None, True))
    return rows


def _round(value: Decimal) -> Decimal:
    """Shop-style prices: whole hryvnias ending in 9."""
    rounded = (value / 10).quantize(Decimal(1), rounding=ROUND_HALF_UP) * 10 - 1
    return rounded.quantize(Decimal("0.01"))
