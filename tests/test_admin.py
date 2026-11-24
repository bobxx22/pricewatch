from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Product
from tests.helpers import PROM_URL, FakeFetcher, load_html

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("model", ["shop", "product", "pricesnapshot"])
def test_changelists_render(admin_client: Client, prom_product: Product, model: str) -> None:
    response = admin_client.get(reverse(f"admin:catalog_{model}_changelist"))

    assert response.status_code == 200


def test_product_change_page_renders(admin_client: Client, prom_product: Product) -> None:
    response = admin_client.get(reverse("admin:catalog_product_change", args=[prom_product.pk]))

    assert response.status_code == 200


def test_adding_a_product_detects_the_shop(admin_client: Client) -> None:
    now = timezone.localtime()
    response = admin_client.post(
        reverse("admin:catalog_product_add"),
        {
            "url": f"{PROM_URL}?utm_source=admin",
            "shop": "",
            "is_active": "on",
            "next_check_at_0": now.strftime("%Y-%m-%d"),
            "next_check_at_1": now.strftime("%H:%M:%S"),
            "snapshots-TOTAL_FORMS": "0",
            "snapshots-INITIAL_FORMS": "0",
            "snapshots-MIN_NUM_FORMS": "0",
            "snapshots-MAX_NUM_FORMS": "1000",
        },
    )

    assert response.status_code == 302, response.context["adminform"].form.errors
    product = Product.objects.get()
    assert product.url == PROM_URL
    assert product.shop.domain == "prom.ua"


def test_check_now_action(
    admin_client: Client, prom_product: Product, use_fake_fetcher: FakeFetcher
) -> None:
    use_fake_fetcher.pages[PROM_URL] = load_html("prom_product.html")

    response = admin_client.post(
        reverse("admin:catalog_product_changelist"),
        {"action": "check_now", "_selected_action": [prom_product.pk]},
        follow=True,
    )

    assert "Checked 1, failed 0." in response.content.decode()
    prom_product.refresh_from_db()
    assert prom_product.price == Decimal("399.00")


@pytest.mark.parametrize("model", ["telegramuser", "subscription"])
def test_bot_changelists_render(admin_client: Client, model: str) -> None:
    response = admin_client.get(reverse(f"admin:bot_{model}_changelist"))

    assert response.status_code == 200
