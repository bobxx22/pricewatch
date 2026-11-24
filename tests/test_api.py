from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.catalog.models import PriceSnapshot, Product, Shop
from tests.helpers import PROM_URL

pytestmark = pytest.mark.django_db


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def staff_api(db: None) -> APIClient:
    user = User.objects.create_user("editor", password="unused-in-token-auth", is_staff=True)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=user).key}")
    return client


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []

    def fake_queue_check(product_id: int) -> bool:
        calls.append(product_id)
        return True

    monkeypatch.setattr("apps.api.views.queue_check", fake_queue_check)
    return calls


@pytest.fixture
def products(prom_shop: Shop) -> list[Product]:
    return [
        Product.objects.create(
            shop=prom_shop, url=f"{PROM_URL}?v={i}", title=f"Товар {i}", price=price, old_price=old
        )
        for i, (price, old) in enumerate([(Decimal(100), None), (Decimal(80), Decimal(100))], 1)
    ]


def test_anyone_can_list_and_filter(api: APIClient, products: list[Product]) -> None:
    everything = api.get("/api/products/").json()
    on_sale = api.get("/api/products/", {"on_sale": "true"}).json()
    cheapest_first = api.get("/api/products/", {"ordering": "price"}).json()

    assert everything["count"] == 2
    assert [p["title"] for p in on_sale["results"]] == ["Товар 2"]
    assert on_sale["results"][0]["discount_percent"] == 20
    assert on_sale["results"][0]["shop"] == "prom.ua"
    assert [p["price"] for p in cheapest_first["results"]] == ["80.00", "100.00"]


def test_history_is_oldest_first(api: APIClient, prom_product: Product) -> None:
    now = timezone.now()
    for days, price in ((3, 120), (1, 99)):
        PriceSnapshot.objects.create(
            product=prom_product,
            price=price,
            is_available=True,
            recorded_at=now - timedelta(days=days),
        )

    data = api.get(f"/api/products/{prom_product.pk}/history/").json()

    assert [point["price"] for point in data["results"]] == ["120.00", "99.00"]


def test_writing_needs_staff(api: APIClient, db: None) -> None:
    anonymous = api.post("/api/products/", {"url": PROM_URL}, format="json")
    User.objects.create_user("viewer", password="x" * 12)
    api.login(username="viewer", password="x" * 12)
    not_staff = api.post("/api/products/", {"url": PROM_URL}, format="json")

    assert anonymous.status_code == 401
    assert not_staff.status_code == 403
    assert not Product.objects.exists()


def test_staff_adds_a_product_and_its_check_is_queued(
    staff_api: APIClient, queued: list[int]
) -> None:
    created = staff_api.post("/api/products/", {"url": f"{PROM_URL}#reviews"}, format="json")
    again = staff_api.post("/api/products/", {"url": PROM_URL}, format="json")

    assert created.status_code == 201
    assert created.json()["url"] == PROM_URL
    assert created.json()["shop"] == "prom.ua"
    assert again.status_code == 200
    assert queued == [created.json()["id"]]


def test_invalid_url_is_rejected(staff_api: APIClient, queued: list[int]) -> None:
    response = staff_api.post("/api/products/", {"url": "ftp://prom.ua/x"}, format="json")

    assert response.status_code == 400
    assert "url" in response.json()


def test_check_action(staff_api: APIClient, prom_product: Product, queued: list[int]) -> None:
    response = staff_api.post(f"/api/products/{prom_product.pk}/check/")

    assert response.status_code == 202
    assert queued == [prom_product.pk]


def test_check_without_broker_returns_the_checked_product(
    staff_api: APIClient, prom_product: Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("apps.api.views.queue_check", lambda product_id: False)

    response = staff_api.post(f"/api/products/{prom_product.pk}/check/")

    assert response.status_code == 200
    assert response.json()["id"] == prom_product.pk


def test_staff_can_pause_but_not_rewrite_scraped_fields(
    staff_api: APIClient, prom_product: Product
) -> None:
    response = staff_api.patch(
        f"/api/products/{prom_product.pk}/", {"is_active": False, "price": "1.00"}, format="json"
    )

    prom_product.refresh_from_db()
    assert response.status_code == 200
    assert prom_product.is_active is False
    assert prom_product.price is None


def test_shops_with_counts(api: APIClient, products: list[Product]) -> None:
    shops = api.get("/api/shops/").json()["results"]

    assert shops == [
        {
            "id": products[0].shop_id,
            "name": "Prom.ua",
            "domain": "prom.ua",
            "is_active": True,
            "product_count": 2,
        }
    ]


def test_schema_and_docs(api: APIClient, db: None) -> None:
    schema = api.get("/api/schema/")
    docs = api.get("/api/docs/")

    assert schema.status_code == 200
    assert b"/api/products/{id}/history/" in schema.content
    assert docs.status_code == 200


def test_token_endpoint(api: APIClient, db: None) -> None:
    User.objects.create_user("bot", password="correct horse battery staple")

    response = api.post(
        "/api/token/",
        {"username": "bot", "password": "correct horse battery staple"},
        format="json",
    )

    assert response.status_code == 200
    assert len(response.json()["token"]) == 40
