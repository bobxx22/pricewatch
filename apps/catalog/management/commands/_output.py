"""Console formatting shared by the catalog commands (modules starting with _ are not commands)."""

from __future__ import annotations

from apps.catalog.models import Product
from apps.catalog.services import CheckOutcome

STOCK_LABELS = {True: "in stock", False: "out of stock", None: "stock unknown"}


def format_outcome(product: Product, outcome: CheckOutcome) -> str:
    name = (product.title or product.url)[:70]
    if not outcome.ok:
        return f"FAIL #{product.pk} {name}: {outcome.error}"

    price = f"{outcome.price} {product.currency}" if outcome.price is not None else "no price"
    notes = []
    if outcome.price_dropped:
        notes.append(f"price dropped from {outcome.previous_price}")
    elif outcome.previous_price is not None and outcome.price != outcome.previous_price:
        notes.append(f"price was {outcome.previous_price}")
    if outcome.back_in_stock:
        notes.append("back in stock")
    suffix = f" [{'; '.join(notes)}]" if notes else ""
    return f"OK   #{product.pk} {name}: {price}, {STOCK_LABELS[outcome.is_available]}{suffix}"
