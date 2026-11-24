from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from django import template
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe

from apps.catalog.formatting import money as format_money
from apps.catalog.formatting import percent_change
from apps.catalog.models import PriceSnapshot
from apps.dashboard.charts import sparkline_path

register = template.Library()

STOCK = {
    True: ("in", "✓", "В наявності"),
    False: ("out", "✕", "Немає"),
    None: ("unknown", "?", "Невідомо"),
}
NO_CHANGE = mark_safe('<span class="change change--none">без змін</span>')
NO_SPARKLINE = mark_safe('<span class="spark spark--empty" aria-hidden="true"></span>')


@register.filter
def money(value: Decimal | None, currency: str = "UAH") -> str:
    return format_money(value, currency or "UAH")


@register.filter
def uk_plural(number: int, forms: str) -> str:
    """Ukrainian plural: {{ n|uk_plural:"товар,товари,товарів" }}."""
    one, few, many = forms.split(",")
    n = abs(int(number))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


@register.filter
def ago(moment: datetime | None) -> str:
    if moment is None:
        return "ще не перевіряли"
    seconds = (timezone.now() - moment).total_seconds()
    if seconds < 60:
        return "щойно"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} хв тому"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} год тому"
    days = hours // 24
    if days < 30:
        return f"{days} {uk_plural(days, 'день,дні,днів')} тому"
    return timezone.localtime(moment).strftime("%d.%m.%Y")


@register.simple_tag
def stock(available: bool | None) -> SafeString:
    css, icon, label = STOCK[available]
    return format_html(
        '<span class="stock stock--{}"><span class="stock__icon" aria-hidden="true">{}</span>'
        '<span class="stock__text">{}</span></span>',
        css,
        icon,
        label,
    )


@register.simple_tag
def delta(previous: Decimal | None, current: Decimal | None) -> SafeString:
    """Arrow, percent and a color for a price change; the words keep it readable without color."""
    change = percent_change(previous, current)
    if change is None or previous == current:
        return NO_CHANGE
    size = f"{abs(change)}%" if change else "<1%"
    if current < previous:
        return format_html(
            '<span class="change change--down"><span aria-hidden="true">▼</span> {}'
            '<span class="visually-hidden"> дешевше</span></span>',
            size,
        )
    return format_html(
        '<span class="change change--up"><span aria-hidden="true">▲</span> {}'
        '<span class="visually-hidden"> дорожче</span></span>',
        size,
    )


@register.simple_tag
def latest_delta(snapshots: Sequence[PriceSnapshot]) -> SafeString:
    """Change between the two latest recorded prices (snapshots are newest first)."""
    prices = [s.price for s in snapshots if s.price is not None]
    if len(prices) < 2:
        return NO_CHANGE
    return delta(prices[1], prices[0])


@register.simple_tag
def sparkline(snapshots: Sequence[PriceSnapshot]) -> SafeString:
    """A tiny step line of the latest price changes (snapshots are newest first)."""
    path = sparkline_path([s.price for s in reversed(snapshots)])
    if path is None:
        return NO_SPARKLINE
    d, end_x, end_y = path
    return format_html(
        '<svg class="spark" viewBox="0 0 72 22" width="72" height="22" aria-hidden="true" '
        'focusable="false"><path class="spark__line" d="{}"/>'
        '<circle class="spark__dot" cx="{}" cy="{}" r="3"/></svg>',
        d,
        end_x,
        end_y,
    )
