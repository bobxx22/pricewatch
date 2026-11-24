from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.catalog.models import PriceSnapshot, Product, Shop
from apps.catalog.services import normalize_url


class ShopSerializer(serializers.ModelSerializer):
    product_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Shop
        fields = ("id", "name", "domain", "is_active", "product_count")


class ProductSerializer(serializers.ModelSerializer):
    shop = serializers.SlugRelatedField(slug_field="domain", read_only=True)
    shop_name = serializers.CharField(source="shop.name", read_only=True)
    discount_percent = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = Product
        fields = (
            "id",
            "url",
            "title",
            "shop",
            "shop_name",
            "price",
            "old_price",
            "discount_percent",
            "currency",
            "is_available",
            "sku",
            "image_url",
            "is_active",
            "last_checked_at",
            "next_check_at",
            "last_error",
            "created_at",
        )
        # Scraped data is owned by the checks; through the API only tracking can be paused.
        read_only_fields = tuple(name for name in fields if name != "is_active")


class ProductCreateSerializer(serializers.Serializer):
    url = serializers.URLField(max_length=1000)

    def validate_url(self, value: str) -> str:
        try:
            return normalize_url(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def create(self, validated_data: dict[str, Any]) -> Any:  # pragma: no cover - not used
        raise NotImplementedError


class PriceSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceSnapshot
        fields = ("price", "old_price", "is_available", "recorded_at")
