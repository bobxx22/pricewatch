from __future__ import annotations

from django.contrib import admin
from django.db.models import Count, QuerySet
from django.http import HttpRequest

from apps.bot.models import Subscription, TelegramUser


class SubscriptionInline(admin.TabularInline):
    model = Subscription
    extra = 0
    fields = ("product", "target_price", "notify_price_drop", "notify_back_in_stock", "created_at")
    readonly_fields = ("product", "created_at")


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ("__str__", "telegram_id", "is_active", "subscription_count", "created_at")
    list_filter = ("is_active",)
    search_fields = ("username", "first_name", "telegram_id")
    readonly_fields = ("telegram_id", "created_at", "updated_at")
    inlines = (SubscriptionInline,)

    def get_queryset(self, request: HttpRequest) -> QuerySet[TelegramUser]:
        return super().get_queryset(request).annotate(subscription_count=Count("subscriptions"))

    @admin.display(description="Subscriptions", ordering="subscription_count")
    def subscription_count(self, obj: TelegramUser) -> int:
        return obj.subscription_count


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "product", "target_price", "notify_price_drop", "created_at")
    list_filter = ("notify_price_drop", "notify_back_in_stock", "product__shop")
    list_select_related = ("user", "product")
    search_fields = ("user__username", "product__title", "product__url")
    autocomplete_fields = ("user",)
    raw_id_fields = ("product",)
