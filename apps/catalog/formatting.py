"""Display helpers shared by the Telegram bot and the dashboard."""

from __future__ import annotations

from decimal import Decimal

THIN_SPACE = " "
CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€"}


def money(value: Decimal | None, currency: str = "UAH") -> str:
    """Ukrainian style for hryvnias ("36 999 ₴", "719,20 ₴"), symbol first for $ and €."""
    if value is None:
        return "—"
    whole = value == value.to_integral_value()
    text = f"{value:,.0f}" if whole else f"{value:,.2f}"
    if currency == "UAH":
        return f"{text.replace(',', THIN_SPACE).replace('.', ',')} ₴"
    symbol = CURRENCY_SYMBOLS.get(currency)
    return f"{symbol}{text}" if symbol else f"{text} {currency}"


def percent_change(old: Decimal | None, new: Decimal | None) -> int | None:
    """Whole-percent change from old to new: -25 means 25% cheaper."""
    if old is None or new is None or old == 0:
        return None
    return round((new - old) / old * 100)
