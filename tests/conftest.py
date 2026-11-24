from __future__ import annotations

import pytest
import requests
from django.test import override_settings

from apps.bot.models import Subscription, TelegramUser
from apps.catalog.models import Product, Shop
from config.celery import app as celery_app
from tests.helpers import PROM_URL, FakeFetcher, FakeTelegram


@pytest.fixture(autouse=True)
def _block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests must never reach real shops; only tests marked `live` may."""
    if request.node.get_closest_marker("live"):
        return

    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Network access in a unit test. Use FakeFetcher or mark the test live.")

    monkeypatch.setattr(requests.Session, "request", refuse)


@pytest.fixture(autouse=True)
def _isolated_side_effects(monkeypatch: pytest.MonkeyPatch):
    """No real broker and no real bot token in tests, whatever .env says."""
    monkeypatch.setitem(celery_app.conf, "task_always_eager", True)
    with override_settings(TELEGRAM_BOT_TOKEN="", DASHBOARD_LOGIN_REQUIRED=False):
        yield


@pytest.fixture
def telegram(monkeypatch: pytest.MonkeyPatch) -> FakeTelegram:
    """Collects the alerts the app would send through the Bot API."""
    fake = FakeTelegram()
    monkeypatch.setattr("apps.bot.telegram_api.get_client", lambda: fake)
    return fake


@pytest.fixture
def fake_fetcher() -> FakeFetcher:
    return FakeFetcher()


@pytest.fixture
def use_fake_fetcher(monkeypatch: pytest.MonkeyPatch, fake_fetcher: FakeFetcher) -> FakeFetcher:
    """Route services.build_fetcher() (used by commands, admin, tasks and the bot) to the fake."""
    monkeypatch.setattr("apps.catalog.services.build_fetcher", lambda: fake_fetcher)
    return fake_fetcher


@pytest.fixture
def prom_shop(db: None) -> Shop:
    return Shop.objects.create(name="Prom.ua", domain="prom.ua")


@pytest.fixture
def prom_product(prom_shop: Shop) -> Product:
    return Product.objects.create(shop=prom_shop, url=PROM_URL)


@pytest.fixture
def tg_user(db: None) -> TelegramUser:
    return TelegramUser.objects.create(telegram_id=1001, username="olena", first_name="Олена")


@pytest.fixture
def subscription(tg_user: TelegramUser, prom_product: Product) -> Subscription:
    return Subscription.objects.create(user=tg_user, product=prom_product)
