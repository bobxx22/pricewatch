"""Product filters shared by the REST API, the dashboard and the exports."""

from __future__ import annotations

import django_filters
from django.db.models import Q, QuerySet

from apps.catalog.models import Product


class ProductFilter(django_filters.FilterSet):
    q = django_filters.CharFilter(method="search", label="Search")
    shop = django_filters.CharFilter(field_name="shop__domain", label="Shop domain")
    in_stock = django_filters.BooleanFilter(field_name="is_available", label="In stock")
    on_sale = django_filters.BooleanFilter(method="filter_on_sale", label="Discounted")
    min_price = django_filters.NumberFilter(field_name="price", lookup_expr="gte")
    max_price = django_filters.NumberFilter(field_name="price", lookup_expr="lte")
    has_error = django_filters.BooleanFilter(method="filter_has_error", label="Last check failed")

    class Meta:
        model = Product
        fields = ("is_active",)

    def search(self, queryset: QuerySet[Product], name: str, value: str) -> QuerySet[Product]:
        value = value.strip()
        if not value:
            return queryset
        return queryset.filter(Q(title__icontains=value) | Q(url__icontains=value) | Q(sku=value))

    def filter_on_sale(
        self, queryset: QuerySet[Product], name: str, value: bool
    ) -> QuerySet[Product]:
        return queryset.filter(old_price__isnull=not value)

    def filter_has_error(
        self, queryset: QuerySet[Product], name: str, value: bool
    ) -> QuerySet[Product]:
        return queryset.exclude(last_error="") if value else queryset.filter(last_error="")
