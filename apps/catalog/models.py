from __future__ import annotations

from datetime import datetime

from django.db import models
from django.utils import timezone


class Shop(models.Model):
    name = models.CharField(max_length=100)
    domain = models.CharField(
        max_length=255, unique=True, help_text="Hostname without www, e.g. prom.ua"
    )
    is_active = models.BooleanField(
        default=True, help_text="Products of inactive shops are not checked."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class ProductQuerySet(models.QuerySet):
    def due_for_check(self, now: datetime | None = None) -> ProductQuerySet:
        return self.filter(
            is_active=True, shop__is_active=True, next_check_at__lte=now or timezone.now()
        )

    def with_discount(self) -> ProductQuerySet:
        """Annotate `discount` (percent off the old price, NULL without a discount)."""
        return self.annotate(
            discount=models.ExpressionWrapper(
                (models.F("old_price") - models.F("price")) * 100 / models.F("old_price"),
                output_field=models.DecimalField(max_digits=6, decimal_places=2),
            )
        )


class Product(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.PROTECT, related_name="products")
    url = models.URLField(max_length=1000, unique=True)
    title = models.CharField(max_length=500, blank=True)
    sku = models.CharField("SKU", max_length=100, blank=True)
    image_url = models.URLField(max_length=1000, blank=True)
    currency = models.CharField(max_length=3, default="UAH")
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    old_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Price before discount, if the shop shows one.",
    )
    is_available = models.BooleanField(
        "in stock", null=True, help_text="Empty until the first successful check."
    )
    is_active = models.BooleanField(default=True, help_text="Inactive products are not checked.")
    last_checked_at = models.DateTimeField(null=True, blank=True)
    next_check_at = models.DateTimeField(default=timezone.now)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = (models.Index(fields=["is_active", "next_check_at"], name="product_due_idx"),)

    def __str__(self) -> str:
        return self.title or self.url

    @property
    def discount_percent(self) -> int | None:
        if self.price is None or not self.old_price:
            return None
        return round((1 - self.price / self.old_price) * 100)


class PriceSnapshotQuerySet(models.QuerySet):
    def with_previous(self) -> PriceSnapshotQuerySet:
        """Annotate the product's previous snapshot price and stock status (NULL for the first)."""
        previous = self.model.objects.filter(
            product=models.OuterRef("product"), recorded_at__lt=models.OuterRef("recorded_at")
        ).order_by("-recorded_at")
        return self.annotate(
            previous_price=models.Subquery(previous.values("price")[:1]),
            previous_available=models.Subquery(previous.values("is_available")[:1]),
        )

    def price_drops(self, since: datetime) -> PriceSnapshotQuerySet:
        return (
            self.with_previous()
            .filter(recorded_at__gte=since, price__lt=models.F("previous_price"))
            .order_by("-recorded_at")
        )


class PriceSnapshot(models.Model):
    """A point in a product's price history.

    Written on the first successful check and then only when the price, the old price
    or the stock status changes, so an unchanged product costs no rows.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="snapshots")
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    old_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_available = models.BooleanField("in stock", null=True)
    recorded_at = models.DateTimeField(default=timezone.now)

    objects = PriceSnapshotQuerySet.as_manager()

    class Meta:
        ordering = ("-recorded_at",)
        get_latest_by = "recorded_at"
        indexes = (
            models.Index(fields=["product", "-recorded_at"], name="snapshot_product_time_idx"),
        )

    def __str__(self) -> str:
        return f"#{self.product_id} at {self.recorded_at:%Y-%m-%d %H:%M}: {self.price}"
