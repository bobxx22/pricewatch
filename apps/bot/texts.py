"""Everything the bot says, in Ukrainian. HTML parse mode: all shop data is escaped."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from html import escape
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

from apps.catalog.formatting import money, percent_change

if TYPE_CHECKING:
    from apps.bot.models import Subscription, TelegramUser
    from apps.bot.services import SubscribeError, SubscribeResult
    from apps.catalog.models import PriceSnapshot

STOCK = {True: "✅ В наявності", False: "❌ Немає в наявності", None: "❔ Наявність невідома"}
STOCK_ICON = {True: "✅", False: "❌", None: "❔"}

COMMANDS = "/list — мої товари\n/help — довідка\n/cancel — скасувати дію"
HELP = (
    "<b>Що я вмію</b>\n\n"
    "• Надішли посилання на товар, і я почну стежити за ціною.\n"
    "• 🎯 Цільова ціна: напишу, лише коли ціна опуститься до неї.\n"
    "• 📈 Історія: як змінювалась ціна.\n"
    "• Перевіряю товари приблизно раз на годину.\n\n"
    "Магазини: Rozetka, Prom.ua, Епіцентр і будь-який магазин зі schema.org розміткою.\n\n"
    f"{COMMANDS}"
)
CHECKING = "⏳ Перевіряю товар…"
SEND_A_LINK = "Надішли посилання на сторінку товару, і я почну стежити за ціною. Довідка: /help"
CANCELLED = "Скасовано."
NOTHING_TO_CANCEL = "Немає чого скасовувати."
NOT_FOUND = "Цього товару вже немає у твоєму списку."
EMPTY_LIST = "Поки що ти ні за чим не стежиш. Надішли посилання на товар."
BAD_PRICE = (
    "Не зрозумів ціну. Надішли число, наприклад <code>1499</code>, або 0, щоб прибрати ціль."
)
SUBSCRIBE_ERRORS = {
    "invalid_url": "Це не схоже на посилання на сторінку товару.",
    "limit": "Досягнуто ліміту в {limit} товарів. Прибери щось зі списку: /list",
    "not_a_product": (
        "Не знайшов на цій сторінці товару з ціною. Надішли посилання саме на сторінку товару."
    ),
    "robots": (
        "Цей магазин забороняє автоматичну перевірку такої сторінки (robots.txt), "
        "тому стежити за нею я не буду."
    ),
    "unavailable": "Сторінка недоступна: магазин не пускає ботів або сторінку видалено.",
}


def welcome(user: TelegramUser) -> str:
    name = escape(user.first_name or "друже")
    return (
        f"Привіт, {name}! 👋\n\n"
        "Я стежу за цінами в інтернет-магазинах і пишу, коли ціна падає "
        "або товар знову з'являється в наявності.\n\n"
        "<b>Як почати:</b> надішли посилання на товар з Rozetka, Prom.ua, Епіцентру "
        "чи іншого магазину.\n\n"
        f"{COMMANDS}"
    )


def card(subscription: Subscription) -> str:
    product = subscription.product
    lines = [f"<b>{_link(product.url, product.title or product.url)}</b>", ""]
    if product.price is not None:
        price = f"💰 <b>{money(product.price, product.currency)}</b>"
        if product.old_price is not None:
            price += f"  <s>{money(product.old_price, product.currency)}</s>"
            price += f"  −{product.discount_percent}%"
        lines.append(price)
    elif product.last_error:
        lines.append("⚠️ Не вдалося перевірити ціну, спробую пізніше.")
    else:
        lines.append("💰 Ціна невідома")
    lines.append(STOCK[product.is_available])
    lines.append(f"🏪 {escape(product.shop.name)}")
    if subscription.target_price is not None:
        lines.append(f"🎯 Ціль: {money(subscription.target_price, product.currency)}")
    if product.last_checked_at is not None:
        lines.append(f"🕒 Перевірено {when(product.last_checked_at)}")
    return "\n".join(lines)


def subscribed(result: SubscribeResult) -> str:
    if not result.created:
        return f"Ти вже стежиш за цим товаром.\n\n{card(result.subscription)}"
    note = "Напишу, коли ціна знизиться або товар з'явиться в наявності."
    if result.outcome is not None and not result.outcome.ok:
        note = "⚠️ Магазин зараз не відповідає. Перевірю ціну пізніше й повідомлю."
    return f"✅ Стежу за товаром!\n\n{card(result.subscription)}\n\n{note}"


def subscribe_error(error: SubscribeError) -> str:
    template = SUBSCRIBE_ERRORS.get(error.code, SUBSCRIBE_ERRORS["unavailable"])
    return template.format(limit=settings.BOT_MAX_SUBSCRIPTIONS)


def subscription_list(subscriptions: Sequence[Subscription]) -> str:
    if not subscriptions:
        return EMPTY_LIST
    lines = [f"<b>Твої товари ({len(subscriptions)}):</b>", ""]
    for number, subscription in enumerate(subscriptions, 1):
        product = subscription.product
        line = (
            f"{number}. {escape(short(product.title or product.url, 55))} — "
            f"<b>{money(product.price, product.currency)}</b> {STOCK_ICON[product.is_available]}"
        )
        if subscription.target_price is not None:
            line += f" 🎯 {money(subscription.target_price, product.currency)}"
        lines.append(line)
    lines += ["", "Натисни номер, щоб відкрити товар."]
    return "\n".join(lines)


def history(subscription: Subscription, snapshots: Sequence[PriceSnapshot]) -> str:
    product = subscription.product
    lines = [f"📈 <b>{escape(short(product.title or product.url, 60))}</b>", ""]
    if not snapshots:
        return "\n".join([*lines, "Історії ще немає: ціну ще не перевіряли."])
    for snapshot in snapshots:
        lines.append(
            f"{when(snapshot.recorded_at)} — {money(snapshot.price, product.currency)} "
            f"{STOCK_ICON[snapshot.is_available]}"
        )
    prices = [s.price for s in snapshots if s.price is not None]
    if len(set(prices)) > 1:
        lines += [
            "",
            f"Мінімум: {money(min(prices), product.currency)} · "
            f"максимум: {money(max(prices), product.currency)}",
        ]
    return "\n".join(lines)


def ask_target(subscription: Subscription) -> str:
    product = subscription.product
    example = int(product.price * Decimal("0.9")) if product.price else 1000
    current = ""
    if subscription.target_price is not None:
        current = f"Зараз ціль: {money(subscription.target_price, product.currency)}.\n"
    return (
        f"🎯 {current}Надішли цільову ціну числом, наприклад <code>{example}</code>. "
        "Напишу, коли ціна буде не вищою.\n\n0 — прибрати ціль, /cancel — скасувати."
    )


def target_saved(subscription: Subscription) -> str:
    product = subscription.product
    if subscription.target_price is None:
        return "Ціль прибрано: напишу про будь-яке зниження ціни."
    target = money(subscription.target_price, product.currency)
    text = f"🎯 Готово! Напишу, коли ціна буде {target} або нижче."
    if product.price is not None and product.price <= subscription.target_price:
        text += "\n\nЦіна вже не вища за ціль, тож наступне зниження теж прийде сповіщенням."
    return text


def unsubscribed(subscription: Subscription) -> str:
    title = subscription.product.title or subscription.product.url
    return f"🗑 Більше не стежу за «{escape(short(title, 60))}»."


def price_alert(subscription: Subscription, event: dict) -> str:
    product = subscription.product
    currency = product.currency
    price = _decimal(event.get("price"))
    previous = _decimal(event.get("previous_price"))
    target = subscription.target_price
    if event.get("back_in_stock"):
        head = "🟢 <b>Знову в наявності!</b>"
    elif target is not None and price is not None and price <= target:
        head = f"🎯 <b>Ціна досягла цілі {money(target, currency)}!</b>"
    else:
        head = "📉 <b>Ціна знизилась!</b>"
    lines = [head, "", _link(product.url, product.title or product.url)]
    change = percent_change(previous, price)
    if event.get("price_dropped") and change is not None:
        lines.append(f"{money(previous, currency)} → <b>{money(price, currency)}</b> ({change}%)")
    elif price is not None:
        lines.append(f"Ціна: <b>{money(price, currency)}</b>")
    lines.append(f"🏪 {escape(product.shop.name)}")
    return "\n".join(lines)


def when(moment: datetime) -> str:
    return timezone.localtime(moment).strftime("%d.%m.%Y %H:%M")


def short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _link(url: str, text: str) -> str:
    return f'<a href="{escape(url, quote=True)}">{escape(text)}</a>'


def _decimal(value: object) -> Decimal | None:
    return Decimal(str(value)) if value not in (None, "") else None
