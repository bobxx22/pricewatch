"""aiogram handlers, driven with stand-in Message and CallbackQuery objects.

async_to_sync runs each handler in an event loop while its sync_to_async database calls
come back to the test's thread, so the usual test transaction still applies.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import User
from asgiref.sync import async_to_sync
from django.core.management import CommandError, call_command

from apps.bot.models import Subscription, TelegramUser
from apps.bot.telegram import handlers
from apps.bot.telegram.callbacks import SubscriptionAction
from apps.bot.telegram.dispatcher import BOT_COMMANDS, build_dispatcher
from apps.bot.telegram.middlewares import UserMiddleware
from apps.bot.telegram.states import TargetPriceForm
from tests.helpers import PROM_URL, FakeFetcher, load_html

pytestmark = pytest.mark.django_db


def message(text: str = "") -> SimpleNamespace:
    progress = SimpleNamespace(edit_text=AsyncMock())
    return SimpleNamespace(text=text, answer=AsyncMock(return_value=progress), progress=progress)


def callback(user: TelegramUser) -> SimpleNamespace:
    # A message too old to edit, so replies go through bot.send_message (easy to inspect).
    return SimpleNamespace(
        message=None,
        from_user=SimpleNamespace(id=user.telegram_id),
        bot=SimpleNamespace(send_message=AsyncMock()),
        answer=AsyncMock(),
    )


def fsm(user: TelegramUser) -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=user.telegram_id, user_id=user.telegram_id)
    return FSMContext(storage=MemoryStorage(), key=key)


def first_text(mock: AsyncMock) -> str:
    return mock.await_args_list[0].args[0] if mock.await_args_list[0].args else ""


def test_start_greets_by_name(tg_user: TelegramUser) -> None:
    msg = message("/start")

    async_to_sync(handlers.start)(msg, tg_user)

    assert "Привіт, Олена!" in first_text(msg.answer)


def test_link_subscribes_and_shows_the_card(
    tg_user: TelegramUser, use_fake_fetcher: FakeFetcher
) -> None:
    use_fake_fetcher.pages[PROM_URL] = load_html("prom_product.html")
    msg = message(f"Ось {PROM_URL}")

    async_to_sync(handlers.track_link)(msg, tg_user)

    assert first_text(msg.answer) == "⏳ Перевіряю товар…"
    reply = msg.progress.edit_text.await_args
    assert reply.args[0].startswith("✅ Стежу за товаром!")
    assert "399 ₴" in reply.args[0]
    assert reply.kwargs["reply_markup"].inline_keyboard[1][0].url == PROM_URL
    assert Subscription.objects.filter(user=tg_user).count() == 1


def test_link_that_is_not_a_product(tg_user: TelegramUser, use_fake_fetcher: FakeFetcher) -> None:
    use_fake_fetcher.pages[PROM_URL] = load_html("no_product.html")
    msg = message(PROM_URL)

    async_to_sync(handlers.track_link)(msg, tg_user)

    assert "Не знайшов на цій сторінці товару" in msg.progress.edit_text.await_args.args[0]


def test_list_shows_numbered_products(subscription: Subscription) -> None:
    msg = message("/list")

    async_to_sync(handlers.show_list)(msg, subscription.user)

    text = first_text(msg.answer)
    markup = msg.answer.await_args.kwargs["reply_markup"]
    assert text.startswith("<b>Твої товари (1):</b>")
    assert markup.inline_keyboard[0][0].text == "1"


def test_target_price_conversation(subscription: Subscription) -> None:
    user = subscription.user
    state = fsm(user)
    button = callback(user)
    data = SubscriptionAction(action="target", id=subscription.pk)

    async_to_sync(handlers.ask_target)(button, data, user, state)
    assert async_to_sync(state.get_state)() == TargetPriceForm.waiting_for_price.state
    assert "Надішли цільову ціну" in button.bot.send_message.await_args.args[1]

    wrong = message("дешевше")
    async_to_sync(handlers.receive_target_price)(wrong, state, user)
    assert "Не зрозумів ціну" in first_text(wrong.answer)

    right = message("350")
    async_to_sync(handlers.receive_target_price)(right, state, user)
    subscription.refresh_from_db()
    assert subscription.target_price == Decimal("350.00")
    assert async_to_sync(state.get_state)() is None
    assert "350 ₴ або нижче" in first_text(right.answer)


def test_card_history_and_delete_buttons(subscription: Subscription) -> None:
    user = subscription.user

    opened = callback(user)
    async_to_sync(handlers.open_card)(
        opened, SubscriptionAction(action="open", id=subscription.pk), user
    )
    history = callback(user)
    async_to_sync(handlers.show_history)(
        history, SubscriptionAction(action="history", id=subscription.pk), user
    )
    deleted = callback(user)
    async_to_sync(handlers.delete_subscription)(
        deleted, SubscriptionAction(action="delete", id=subscription.pk), user
    )
    gone = callback(user)
    async_to_sync(handlers.open_card)(
        gone, SubscriptionAction(action="open", id=subscription.pk), user
    )

    assert "🏪 Prom.ua" in opened.bot.send_message.await_args.args[1]
    assert "Історії ще немає" in history.bot.send_message.await_args.args[1]
    assert deleted.bot.send_message.await_args.args[1].startswith("🗑 Більше не стежу")
    assert not Subscription.objects.exists()
    gone.answer.assert_awaited_once()
    assert gone.answer.await_args.kwargs == {"show_alert": True}


def test_cancel_and_fallback(tg_user: TelegramUser) -> None:
    state = fsm(tg_user)
    nothing = message("/cancel")
    async_to_sync(handlers.cancel)(nothing, state)
    async_to_sync(state.set_state)(TargetPriceForm.waiting_for_price)
    something = message("/cancel")
    async_to_sync(handlers.cancel)(something, state)
    other = message("привіт")
    async_to_sync(handlers.fallback)(other)

    assert first_text(nothing.answer) == "Немає чого скасовувати."
    assert first_text(something.answer) == "Скасовано."
    assert "Надішли посилання" in first_text(other.answer)


def test_middleware_registers_the_sender(db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # Inside a test transaction a real close_old_connections() would drop the connection.
    monkeypatch.setattr("apps.bot.telegram.middlewares.close_old_connections", lambda: None)
    handler = AsyncMock(return_value="handled")
    sender = User(id=555, is_bot=False, first_name="Ірина", username="iryna", language_code="uk")

    result = async_to_sync(UserMiddleware())(handler, object(), {"event_from_user": sender})

    assert result == "handled"
    tg_user = handler.await_args.args[1]["tg_user"]
    assert (tg_user.telegram_id, tg_user.username) == (555, "iryna")


def test_dispatcher_and_commands() -> None:
    dispatcher = build_dispatcher()

    assert handlers.router in dispatcher.sub_routers
    assert [c.command for c in BOT_COMMANDS] == ["list", "help", "cancel"]
    assert "callback_query" in dispatcher.resolve_used_update_types()


def test_runbot_needs_a_token() -> None:
    with pytest.raises(CommandError, match="TELEGRAM_BOT_TOKEN"):
        call_command("runbot")


def test_startup_calls_wait_out_telegram_flood_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiogram.exceptions import TelegramRetryAfter
    from aiogram.methods import GetMe

    from apps.bot.telegram import dispatcher

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(dispatcher.asyncio, "sleep", fake_sleep)
    flood = TelegramRetryAfter(method=GetMe(), message="Too Many Requests", retry_after=19)
    call = AsyncMock(side_effect=[flood, "me"])

    assert async_to_sync(dispatcher.with_retry_after)(call) == "me"
    assert sleeps == [20]

    always = AsyncMock(side_effect=flood)
    with pytest.raises(TelegramRetryAfter):
        async_to_sync(dispatcher.with_retry_after)(always, attempts=2)
