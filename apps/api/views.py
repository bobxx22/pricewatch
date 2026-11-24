from __future__ import annotations

from typing import Any

from django.db.models import Count, QuerySet
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from apps.api.serializers import (
    PriceSnapshotSerializer,
    ProductCreateSerializer,
    ProductSerializer,
    ShopSerializer,
)
from apps.catalog import services
from apps.catalog.filters import ProductFilter
from apps.catalog.models import Product, Shop
from apps.catalog.tasks import queue_check


class ShopViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Shop.objects.annotate(product_count=Count("products")).order_by("name")
    serializer_class = ShopSerializer
    filterset_fields = ("is_active",)
    search_fields = ("name", "domain")
    ordering_fields = ("name", "product_count")


class ProductViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Tracked products. Reading is public; adding, pausing and deleting need staff."""

    queryset = Product.objects.select_related("shop").with_discount().order_by("-created_at")
    serializer_class = ProductSerializer
    filterset_class = ProductFilter
    ordering_fields = ("price", "discount", "title", "last_checked_at", "created_at")
    http_method_names = ("get", "post", "patch", "delete", "head", "options")

    def get_serializer_class(self) -> type[BaseSerializer]:
        if self.action == "create":
            return ProductCreateSerializer
        if self.action == "history":
            return PriceSnapshotSerializer
        return ProductSerializer

    @extend_schema(
        request=ProductCreateSerializer,
        responses={
            201: ProductSerializer,
            200: OpenApiResponse(ProductSerializer, description="Already tracked"),
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Start tracking a product URL; its first price check is queued."""
        serializer = ProductCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product, created = services.add_product(serializer.validated_data["url"])
        if created:
            queue_check(product.pk)
        product = self.get_queryset().get(pk=product.pk)
        return Response(
            ProductSerializer(product, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(responses=PriceSnapshotSerializer(many=True))
    @action(detail=True, methods=["get"], filterset_class=None, ordering_fields=None)
    def history(self, request: Request, pk: str | None = None) -> Response:
        """Price history, oldest first. A point exists for every change of price or stock."""
        snapshots: QuerySet = self.get_object().snapshots.order_by("recorded_at")
        page = self.paginate_queryset(snapshots)
        serializer = PriceSnapshotSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        request=None,
        responses={
            202: OpenApiResponse(description="Check queued for a worker"),
            200: OpenApiResponse(ProductSerializer, description="No broker: checked right away"),
        },
    )
    @action(detail=True, methods=["post"])
    def check(self, request: Request, pk: str | None = None) -> Response:
        """Check the price now instead of waiting for the schedule."""
        product = self.get_object()
        if queue_check(product.pk):
            return Response({"status": "queued"}, status=status.HTTP_202_ACCEPTED)
        product = self.get_queryset().get(pk=product.pk)
        return Response(ProductSerializer(product, context=self.get_serializer_context()).data)
