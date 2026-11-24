from __future__ import annotations

from typing import Any

from django.contrib import admin, messages
from django.db.models import Count, QuerySet
from django.http import HttpRequest

from apps.catalog import services
from apps.catalog.models import PriceSnapshot, Product, Shop

MAX_SYNC_CHECKS = 20


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ("name", "domain", "is_active", "product_count", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "domain")

    def get_queryset(self, request: HttpRequest) -> QuerySet[Shop]:
        return super().get_queryset(request).annotate(product_count=Count("products"))

    @admin.display(description="Products", ordering="product_count")
    def product_count(self, obj: Shop) -> int:
        return obj.product_count


class PriceSnapshotInline(admin.TabularInline):
    model = PriceSnapshot
    extra = 0
    can_delete = False
    fields = ("recorded_at", "price", "old_price", "is_available")
    readonly_fields = fields
    ordering = ("-recorded_at",)

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "shop",
        "price",
        "old_price",
        "currency",
        "is_available",
        "last_checked_at",
        "has_error",
        "is_active",
    )
    list_filter = ("shop", "is_available", "is_active")
    search_fields = ("title", "url", "sku")
    list_select_related = ("shop",)
    readonly_fields = (
        "title",
        "sku",
        "image_url",
        "currency",
        "price",
        "old_price",
        "is_available",
        "last_checked_at",
        "last_error",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("url", "shop", "is_active", "next_check_at")}),
        (
            "Last check",
            {
                "fields": (
                    "title",
                    "price",
                    "old_price",
                    "currency",
                    "is_available",
                    "sku",
                    "image_url",
                    "last_checked_at",
                    "last_error",
                )
            },
        ),
        ("Record", {"fields": ("created_at", "updated_at")}),
    )
    inlines = (PriceSnapshotInline,)
    actions = ("check_now",)

    @admin.display(description="Error", boolean=True)
    def has_error(self, obj: Product) -> bool:
        return bool(obj.last_error)

    def get_form(self, request: HttpRequest, obj: Product | None = None, **kwargs: Any) -> Any:
        form = super().get_form(request, obj, **kwargs)
        if obj is None:
            shop_field = form.base_fields["shop"]
            shop_field.required = False
            shop_field.help_text = "Leave empty to detect the shop from the URL."
        return form

    def save_model(self, request: HttpRequest, obj: Product, form: Any, change: bool) -> None:
        if not change:
            obj.url = services.normalize_url(obj.url)
            if obj.shop_id is None:
                obj.shop = services.get_or_create_shop(obj.url)
        super().save_model(request, obj, form, change)

    @admin.action(description=f"Check prices now (up to {MAX_SYNC_CHECKS} products)")
    def check_now(self, request: HttpRequest, queryset: QuerySet[Product]) -> None:
        products = list(queryset.select_related("shop")[: MAX_SYNC_CHECKS + 1])
        if len(products) > MAX_SYNC_CHECKS:
            self.message_user(
                request,
                f"Select at most {MAX_SYNC_CHECKS} products: checks run while you wait.",
                messages.WARNING,
            )
            return
        fetcher = services.build_fetcher()
        failed = 0
        for product in products:
            outcome = services.check_product(product, fetcher=fetcher)
            if not outcome.ok:
                failed += 1
                self.message_user(request, f"{product}: {outcome.error}", messages.ERROR)
        level = messages.WARNING if failed else messages.SUCCESS
        self.message_user(request, f"Checked {len(products)}, failed {failed}.", level)


@admin.register(PriceSnapshot)
class PriceSnapshotAdmin(admin.ModelAdmin):
    list_display = ("product", "price", "old_price", "is_available", "recorded_at")
    list_filter = ("product__shop", "is_available")
    list_select_related = ("product",)
    search_fields = ("product__title", "product__url")
    date_hierarchy = "recorded_at"
    readonly_fields = ("product", "price", "old_price", "is_available", "recorded_at")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False
