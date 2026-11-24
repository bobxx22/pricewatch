import csv
import io
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from openpyxl import load_workbook

from apps.catalog.models import Product, Shop

pytestmark = pytest.mark.django_db


@pytest.fixture
def demo(db: None) -> None:
    call_command("seed_demo", stdout=io.StringIO())


def test_index_shows_tags_summary_and_rows(client: Client, demo: None) -> None:
    response = client.get(reverse("dashboard:index"))

    page = response.content.decode()
    assert response.status_code == 200
    assert "Подешевшало за тиждень" in page
    assert page.count('class="tag"') == 5
    assert "Під наглядом <strong>8</strong> товарів" in page
    assert page.count('class="product__title"') == 8


def test_index_has_no_query_per_row(
    client: Client, demo: None, django_assert_max_num_queries: object
) -> None:
    with django_assert_max_num_queries(12):  # type: ignore[operator]
        client.get(reverse("dashboard:index"))


def test_without_recent_drops_the_tags_show_current_discounts(
    client: Client, prom_product: Product
) -> None:
    Product.objects.filter(pk=prom_product.pk).update(
        title="Олія", price=Decimal(399), old_price=Decimal(935)
    )

    page = client.get(reverse("dashboard:index")).content.decode()

    assert "Найбільші знижки зараз" in page
    assert "−57%" in page


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ({"q": "LEGO"}, 1),
        ({"shop": "demo.pricewatch.example"}, 8),
        ({"shop": "prom.ua"}, 0),
        ({"on_sale": "true", "in_stock": "true"}, None),
        ({"sort": "price"}, 8),
    ],
)
def test_filters(client: Client, demo: None, query: dict, expected: int | None) -> None:
    response = client.get(reverse("dashboard:index"), query)

    rows = response.context["products"]
    if expected is None:
        assert all(p.old_price and p.is_available for p in rows)
    else:
        assert len(rows) == expected
    if query.get("sort") == "price":
        prices = [p.price for p in rows]
        assert prices == sorted(prices)


def test_product_page_has_chart_and_changes(client: Client, demo: None) -> None:
    product = Product.objects.get(title__contains="LEGO")

    response = client.get(reverse("dashboard:product", args=[product.pk]))

    page = response.content.decode()
    assert response.status_code == 200
    assert page.count('class="chart__line"') == 2  # wide and compact versions
    assert 'id="chart-points-wide"' in page
    assert page.count("<tr>") - 1 == product.snapshots.count()


def test_product_page_without_history(client: Client, prom_product: Product) -> None:
    page = client.get(reverse("dashboard:product", args=[prom_product.pk])).content.decode()

    assert "Графік з'явиться після першої вдалої перевірки ціни." in page


def test_unknown_product_is_404(client: Client, db: None) -> None:
    assert client.get(reverse("dashboard:product", args=[999])).status_code == 404


def test_csv_export_is_excel_friendly_and_formula_safe(client: Client, prom_shop: Shop) -> None:
    Product.objects.create(
        shop=prom_shop, url="https://prom.ua/p1", title='=HYPERLINK("http://evil")', price=10
    )
    Product.objects.create(shop=prom_shop, url="https://prom.ua/p2", title="Олія", price=399)

    response = client.get(reverse("dashboard:export", args=["csv"]), {"q": "Олія"})

    body = response.content.decode("utf-8")
    assert response["Content-Disposition"].startswith('attachment; filename="pricewatch-')
    assert body.startswith("﻿")
    rows = list(csv.reader(io.StringIO(body.lstrip("﻿"))))
    assert rows[0][:3] == ["ID", "Товар", "Магазин"]
    assert [row[1] for row in rows[1:]] == ["Олія"]

    everything = client.get(reverse("dashboard:export", args=["csv"])).content.decode("utf-8")
    assert "'=HYPERLINK" in everything


def test_xlsx_export(client: Client, prom_shop: Shop) -> None:
    Product.objects.create(
        shop=prom_shop,
        url="https://prom.ua/p1",
        title="+SUM(A1:A2)",
        price=Decimal("399.50"),
        old_price=Decimal(500),
        is_available=True,
    )

    response = client.get(reverse("dashboard:export", args=["xlsx"]))

    sheet = load_workbook(io.BytesIO(response.content)).active
    assert sheet.title == "Товари"
    assert sheet["B1"].value == "Товар"
    assert sheet["B2"].value == "'+SUM(A1:A2)"
    assert sheet["B2"].data_type == "s"
    assert sheet["D2"].value == 399.5
    assert sheet["F2"].value == 20  # discount, %
    assert sheet["J2"].hyperlink.target == "https://prom.ua/p1"


def test_unknown_export_format(client: Client, db: None) -> None:
    assert client.get(reverse("dashboard:export", args=["pdf"])).status_code == 404


def test_login_can_be_required(client: Client, db: None, settings: object) -> None:
    settings.DASHBOARD_LOGIN_REQUIRED = True  # type: ignore[attr-defined]

    response = client.get(reverse("dashboard:index"))

    assert response.status_code == 302
    assert response["Location"].startswith(reverse("admin:login"))
