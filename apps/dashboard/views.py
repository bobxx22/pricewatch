from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.db.models import Count, F, Prefetch, Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.utils import timezone
from django.views.generic import DetailView, ListView, View

from apps.catalog.filters import ProductFilter
from apps.catalog.formatting import percent_change
from apps.catalog.models import PriceSnapshot, Product, Shop
from apps.dashboard import exports
from apps.dashboard.charts import ChartPoint, build_price_chart

SPARK_POINTS = 12
TAG_COUNT = 5  # one shelf row on a desktop screen
DROPS_WINDOW = timedelta(days=7)
SORTS = {
    "new": ("Нові спочатку", ("-created_at",)),
    "discount": ("Найбільша знижка", (F("discount").desc(nulls_last=True), "title")),
    "price": ("Дешевші спочатку", (F("price").asc(nulls_last=True), "title")),
    "-price": ("Дорожчі спочатку", (F("price").desc(nulls_last=True), "title")),
    "title": ("За назвою", ("title",)),
}


@dataclass(frozen=True)
class PriceTag:
    """One yellow shelf tag in the "got cheaper" strip."""

    product_id: int
    title: str
    shop: str
    price: Decimal
    was: Decimal
    percent: int  # negative: -28 means 28% cheaper
    currency: str

    @property
    def off(self) -> int:
        return abs(self.percent)


class DashboardAccessMixin:
    """Public by default; DASHBOARD_LOGIN_REQUIRED=true puts it behind the admin login."""

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if settings.DASHBOARD_LOGIN_REQUIRED and not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]


def filtered_products(request: HttpRequest) -> tuple[ProductFilter, QuerySet[Product]]:
    """Products matching the request's filters and sort order, shared by the page and exports."""
    queryset = Product.objects.select_related("shop").with_discount()
    product_filter = ProductFilter(request.GET or None, queryset=queryset)
    if product_filter.is_bound and product_filter.is_valid():
        queryset = product_filter.qs
    _, ordering = SORTS.get(request.GET.get("sort", ""), SORTS["new"])
    return product_filter, queryset.order_by(*ordering)


class ProductListView(DashboardAccessMixin, ListView):
    template_name = "dashboard/index.html"
    context_object_name = "products"
    paginate_by = 25

    def get_queryset(self) -> QuerySet[Product]:
        self.product_filter, queryset = filtered_products(self.request)
        # One extra query for every row's sparkline: a sliced prefetch (window function).
        recent = PriceSnapshot.objects.order_by("-recorded_at")[:SPARK_POINTS]
        return queryset.prefetch_related(
            Prefetch("snapshots", queryset=recent, to_attr="recent_snapshots")
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        tags = recent_drops()
        tags_title = "Подешевшало за тиждень"
        if not tags:
            tags, tags_title = biggest_discounts(), "Найбільші знижки зараз"
        query = self.request.GET.copy()
        query.pop("page", None)
        context.update(
            tags=tags,
            tags_title=tags_title,
            summary=summary(),
            shops=Shop.objects.filter(products__isnull=False).distinct().order_by("name"),
            sorts=[(key, label) for key, (label, _) in SORTS.items()],
            current=self.request.GET,
            is_filtered=any(value for key, value in self.request.GET.items() if key != "page"),
            query=query.urlencode(),
        )
        return context


class ProductDetailView(DashboardAccessMixin, DetailView):
    template_name = "dashboard/product_detail.html"
    context_object_name = "product"

    def get_queryset(self) -> QuerySet[Product]:
        return Product.objects.select_related("shop").with_discount()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        product: Product = self.object
        snapshots = list(product.snapshots.with_previous().order_by("recorded_at"))
        points = [ChartPoint(s.recorded_at, s.price, s.is_available) for s in snapshots]
        prices = [s for s in snapshots if s.price is not None]
        context.update(
            chart=build_price_chart(points, currency=product.currency, width=760, height=280),
            chart_compact=build_price_chart(
                points, currency=product.currency, width=380, height=240
            ),
            changes=list(reversed(snapshots)),
            lowest=min(prices, key=lambda s: (s.price, s.recorded_at), default=None),
            highest=max(prices, key=lambda s: (s.price, s.recorded_at), default=None),
            has_bands=any(s.is_available is False for s in snapshots),
        )
        return context


class ExportView(DashboardAccessMixin, View):
    """/export/products.csv and .xlsx: the dashboard's current filters, every page."""

    def get(
        self, request: HttpRequest, *args: Any, fmt: str = "csv", **kwargs: Any
    ) -> HttpResponse:
        _, products = filtered_products(request)
        if fmt == "csv":
            return exports.csv_response(products)
        if fmt == "xlsx":
            return exports.xlsx_response(products)
        raise Http404("Unknown export format")


def recent_drops(window: timedelta = DROPS_WINDOW, limit: int = TAG_COUNT) -> list[PriceTag]:
    """The biggest price drop of each product in the window, steepest first."""
    since = timezone.now() - window
    drops = (
        PriceSnapshot.objects.price_drops(since)
        .filter(product__is_active=True)
        .select_related("product__shop")[:200]
    )
    latest: dict[int, PriceTag] = {}
    for snapshot in drops:
        if snapshot.product_id in latest:
            continue
        product = snapshot.product
        latest[snapshot.product_id] = PriceTag(
            product_id=product.pk,
            title=product.title or product.url,
            shop=product.shop.name,
            price=snapshot.price,
            was=snapshot.previous_price,
            percent=percent_change(snapshot.previous_price, snapshot.price) or 0,
            currency=product.currency,
        )
    return sorted(latest.values(), key=lambda tag: tag.percent)[:limit]


def biggest_discounts(limit: int = TAG_COUNT) -> list[PriceTag]:
    products = (
        Product.objects.filter(is_active=True, price__isnull=False, old_price__isnull=False)
        .select_related("shop")
        .with_discount()
        .order_by("-discount")[:limit]
    )
    return [
        PriceTag(
            product_id=p.pk,
            title=p.title or p.url,
            shop=p.shop.name,
            price=p.price,
            was=p.old_price,
            percent=percent_change(p.old_price, p.price) or 0,
            currency=p.currency,
        )
        for p in products
    ]


def summary() -> dict[str, int]:
    counts = Product.objects.filter(is_active=True).aggregate(
        total=Count("pk"),
        shops=Count("shop", distinct=True),
        in_stock=Count("pk", filter=Q(is_available=True)),
        on_sale=Count("pk", filter=Q(old_price__isnull=False)),
    )
    since = timezone.now() - DROPS_WINDOW
    counts["dropped"] = (
        PriceSnapshot.objects.price_drops(since).values("product").distinct().count()
    )
    return counts
