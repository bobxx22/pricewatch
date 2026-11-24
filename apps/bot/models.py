from __future__ import annotations

from decimal import Decimal

from django.db import models

from apps.catalog.models import Product


class TelegramUser(models.Model):
    telegram_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=64, blank=True)
    first_name = models.CharField(max_length=128, blank=True)
    language_code = models.CharField(max_length=16, blank=True)
    is_active = models.BooleanField(
        default=True,
        help_text="Cleared when the user blocks the bot, set again when they write to it.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Telegram user"

    def __str__(self) -> str:
        return f"@{self.username}" if self.username else self.first_name or str(self.telegram_id)


class Subscription(models.Model):
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name="subscriptions")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="subscriptions")
    target_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Alert about drops only once the price is at or below this.",
    )
    notify_price_drop = models.BooleanField(default=True)
    notify_back_in_stock = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = (
            models.UniqueConstraint(fields=("user", "product"), name="unique_subscription"),
        )

    def __str__(self) -> str:
        return f"{self.user} -> {self.product}"

    def wants_alert(
        self, *, price_dropped: bool, back_in_stock: bool, price: Decimal | None
    ) -> bool:
        if back_in_stock and self.notify_back_in_stock:
            return True
        if price_dropped and self.notify_price_drop:
            return self.target_price is None or (price is not None and price <= self.target_price)
        return False
