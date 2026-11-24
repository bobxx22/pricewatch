"""Catalog events. Other apps subscribe to them, so the catalog never imports those apps."""

from django.dispatch import Signal

# Sent after a successful check when the price dropped or the product came back in stock.
# Keyword arguments: product (Product), outcome (services.CheckOutcome).
product_changed = Signal()
