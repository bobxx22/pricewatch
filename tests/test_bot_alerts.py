from decimal import Decimal
from types import SimpleNamespace

import pytest
import requests

from apps.bot.models import Subscription, TelegramUser
from apps.bot.notifications import send_price_alerts
from apps.bot.telegram_api import BotBlockedError, TelegramApiError, TelegramClient
from apps.catalog.services import apply_result
from scraping import ParseResult
from tests.helpers import FakeTelegram

pytestmark = pytest.mark.django_db

DROP = {"price": "90.00", "previous_price": "100.00", "price_dropped": True, "back_in_stock": False}


def test_price_drop_reaches_subscribers_through_the_signal(
    subscription: Subscription, telegram: FakeTelegram, django_capture_on_commit_callbacks: object
) -> None:
    product = subscription.product
    apply_result(product, ParseResult(title="Олія", price=Decimal(100), is_available=True))

    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        apply_result(product, ParseResult(title="Олія", price=Decimal(90), is_available=True))

    assert len(telegram.sent) == 1
    message = telegram.sent[0]
    assert message["chat_id"] == subscription.user.telegram_id
    assert "📉 <b>Ціна знизилась!</b>" in message["text"]
    assert "100 ₴ → <b>90 ₴</b> (-10%)" in message["text"]
    buttons = [b["text"] for row in message["reply_markup"]["inline_keyboard"] for b in row]
    assert "🗑 Відписатися" in buttons


def test_no_alert_for_a_price_rise_or_without_subscribers(
    prom_product: object, telegram: FakeTelegram, django_capture_on_commit_callbacks: object
) -> None:
    apply_result(prom_product, ParseResult(title="Олія", price=Decimal(100), is_available=True))

    with django_capture_on_commit_callbacks(execute=True) as callbacks:  # type: ignore[operator]
        apply_result(prom_product, ParseResult(title="Олія", price=Decimal(90), is_available=True))

    assert callbacks == []
    assert telegram.sent == []


def test_target_price_filters_and_headlines_alerts(
    subscription: Subscription, telegram: FakeTelegram
) -> None:
    other_user = TelegramUser.objects.create(telegram_id=2002)
    Subscription.objects.create(user=other_user, product=subscription.product, target_price=80)
    Subscription.objects.filter(pk=subscription.pk).update(target_price=95)

    sent = send_price_alerts(subscription.product_id, DROP)

    assert sent == 1
    assert telegram.sent[0]["chat_id"] == subscription.user.telegram_id
    assert "🎯 <b>Ціна досягла цілі 95 ₴!</b>" in telegram.sent[0]["text"]


def test_back_in_stock_alert(subscription: Subscription, telegram: FakeTelegram) -> None:
    event = {
        "price": "100.00",
        "previous_price": "100.00",
        "price_dropped": False,
        "back_in_stock": True,
    }

    send_price_alerts(subscription.product_id, event)

    assert "🟢 <b>Знову в наявності!</b>" in telegram.sent[0]["text"]


def test_users_who_blocked_the_bot_are_switched_off(
    subscription: Subscription, telegram: FakeTelegram
) -> None:
    telegram.failures[subscription.user.telegram_id] = BotBlockedError(
        "bot was blocked by the user"
    )

    assert send_price_alerts(subscription.product_id, DROP) == 0
    subscription.user.refresh_from_db()
    assert subscription.user.is_active is False
    assert send_price_alerts(subscription.product_id, DROP) == 0  # not even tried again


def test_one_failed_message_does_not_stop_the_rest(
    subscription: Subscription, telegram: FakeTelegram
) -> None:
    second = TelegramUser.objects.create(telegram_id=3003)
    Subscription.objects.create(user=second, product=subscription.product)
    telegram.failures[subscription.user.telegram_id] = TelegramApiError("Bad Request")

    assert send_price_alerts(subscription.product_id, DROP) == 1
    assert telegram.sent[0]["chat_id"] == 3003


def test_without_a_token_alerts_are_skipped(subscription: Subscription) -> None:
    assert send_price_alerts(subscription.product_id, DROP) == 0


# --- The Bot API client -----------------------------------------------------------


class FakeSession:
    def __init__(self, reply: dict | Exception) -> None:
        self.reply = reply
        self.posts: list[tuple[str, dict]] = []

    def post(self, url: str, json: dict, timeout: float) -> SimpleNamespace:
        self.posts.append((url, json))
        if isinstance(self.reply, Exception):
            raise self.reply
        return SimpleNamespace(json=lambda: self.reply)


TOKEN = "123456:TEST-token-not-real"


def test_client_sends_html_messages_without_link_previews() -> None:
    session = FakeSession({"ok": True, "result": {}})

    TelegramClient(TOKEN, session=session).send_message(5, "<b>Hi</b>", reply_markup={"x": 1})

    url, payload = session.posts[0]
    assert url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert payload == {
        "chat_id": 5,
        "text": "<b>Hi</b>",
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "reply_markup": {"x": 1},
    }


def test_client_errors() -> None:
    blocked = FakeSession(
        {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked"}
    )
    flood = FakeSession(
        {
            "ok": False,
            "error_code": 429,
            "description": "Too Many Requests",
            "parameters": {"retry_after": 7},
        }
    )

    with pytest.raises(BotBlockedError):
        TelegramClient(TOKEN, session=blocked).send_message(5, "x")
    with pytest.raises(TelegramApiError) as error:
        TelegramClient(TOKEN, session=flood).send_message(5, "x")
    assert error.value.retry_after == 7


def test_network_errors_never_leak_the_token() -> None:
    failing = FakeSession(
        requests.ConnectionError(f"Max retries exceeded with url: /bot{TOKEN}/sendMessage")
    )

    with pytest.raises(TelegramApiError) as error:
        TelegramClient(TOKEN, session=failing).send_message(5, "x")

    assert TOKEN not in str(error.value)
    assert "/bot<token>/sendMessage" in str(error.value)
