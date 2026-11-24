"""Server-side SVG geometry for price charts, so pages need no charting library.

Prices change in steps (a shop relabels the shelf), so the line is drawn step-after:
flat until the next recorded change. Colors come from CSS classes, which makes light
and dark themes a stylesheet concern.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.catalog.formatting import money

STOCK_LABELS = {True: "в наявності", False: "немає в наявності", None: "наявність невідома"}


@dataclass(frozen=True)
class ChartPoint:
    at: datetime
    price: Decimal | None
    available: bool | None


@dataclass(frozen=True)
class Tick:
    position: str
    label: str


@dataclass(frozen=True)
class Marker:
    x: str
    y: str
    label: str
    label_x: str
    label_y: str
    anchor: str


@dataclass(frozen=True)
class Band:
    x: str
    width: str


@dataclass
class PriceChart:
    width: int
    height: int
    left: float
    top: float
    right: float
    bottom: float
    line_path: str
    y_ticks: list[Tick] = field(default_factory=list)
    x_ticks: list[Tick] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    bands: list[Band] = field(default_factory=list)
    points: list[dict] = field(default_factory=list)  # tooltip data, rendered with json_script
    summary: str = ""

    @property
    def plot_height(self) -> str:
        return _f(self.bottom - self.top)

    @property
    def tick_label_x(self) -> str:
        return _f(self.left - 10)

    @property
    def x_label_y(self) -> str:
        return _f(self.bottom + 22)


def build_price_chart(
    points: Sequence[ChartPoint],
    *,
    currency: str = "UAH",
    now: datetime | None = None,
    width: int = 880,
    height: int = 300,
) -> PriceChart | None:
    """A step chart of `points` (oldest first), extended to `now`. None without prices."""
    priced = [p for p in points if p.price is not None]
    if not priced:
        return None
    now = now or timezone.now()
    start = points[0].at
    end = max(now, points[-1].at)
    if end <= start:
        end = start + timedelta(hours=1)

    compact = width < 500
    left = 52.0 if compact else 72.0
    right = width - (72.0 if compact else 96.0)  # room for the current-price label
    top, bottom = 20.0, height - 36.0
    values = [float(p.price) for p in priced]
    ticks = nice_ticks(min(values), max(values), count=3 if compact else 4)
    low, high = ticks[0], ticks[-1]

    def x_of(moment: datetime) -> float:
        return left + (moment - start) / (end - start) * (right - left)

    def y_of(value: float) -> float:
        return bottom - (value - low) / (high - low) * (bottom - top)

    chart = PriceChart(width, height, left, top, right, bottom, line_path="")
    chart.y_ticks = [Tick(_f(y_of(t)), axis_label(t, high)) for t in ticks]
    chart.x_ticks = [
        Tick(_f(x_of(t)), date_label(t, end - start))
        for t in time_ticks(start, end, count=3 if compact else 5)
    ]
    chart.line_path = _step_path(points, x_of, y_of, end)
    chart.bands = _out_of_stock_bands(points, x_of, end)
    chart.markers = _markers(points, x_of, y_of, end, currency, top=top, bottom=bottom)
    chart.points = [
        {
            "x": round(x_of(p.at), 1),
            "y": round(y_of(float(p.price)), 1) if p.price is not None else None,
            "price": money(p.price, currency) if p.price is not None else "без ціни",
            "date": timezone.localtime(p.at).strftime("%d.%m.%Y %H:%M"),
            "stock": STOCK_LABELS[p.available],
        }
        for p in points
    ]
    first, last = priced[0], priced[-1]
    chart.summary = (
        f"Ціна з {timezone.localtime(first.at):%d.%m.%Y} до сьогодні: від "
        f"{money(Decimal(str(min(values))), currency)} "
        f"до {money(Decimal(str(max(values))), currency)}, "
        f"зараз {money(last.price, currency)}."
    )
    return chart


def sparkline_path(
    prices: Sequence[Decimal | None], *, width: int = 72, height: int = 22, pad: float = 4.0
) -> tuple[str, str, str] | None:
    """A step path over evenly spaced price changes (oldest first), plus its end point."""
    values = [float(p) for p in prices if p is not None]
    if len(values) < 2:
        return None
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    step = (width - 2 * pad) / (len(values) - 1)

    def y_of(value: float) -> float:
        return (
            height - pad - (value - low) / span * (height - 2 * pad) if high != low else height / 2
        )

    parts = [f"M{_f(pad)} {_f(y_of(values[0]))}"]
    for index, value in enumerate(values[1:], 1):
        parts.append(f"H{_f(pad + index * step)}V{_f(y_of(value))}")
    return "".join(parts), _f(pad + (len(values) - 1) * step), _f(y_of(values[-1]))


def nice_ticks(low: float, high: float, count: int = 4) -> list[float]:
    """Round tick values (1, 2, 2.5 or 5 times a power of ten) that cover low..high."""
    if low == high:
        pad = max(abs(low) * 0.05, 1.0)
        low, high = low - pad, high + pad
    raw = (high - low) / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if raw <= m * magnitude)
    first = math.floor(low / step) * step
    last = math.ceil(high / step) * step
    return [first + i * step for i in range(round((last - first) / step) + 1)]


def axis_label(value: float, top: float) -> str:
    """Full numbers under 10 000, compact ("36,5 тис.") on an axis that reaches it."""
    if top >= 10_000:
        thousands = value / 1000
        text = f"{thousands:.1f}".rstrip("0").rstrip(".")
        return f"{text.replace('.', ',')} тис."
    text = f"{value:,.2f}".rstrip("0").rstrip(".")
    return text.replace(",", " ").replace(".", ",")


def time_ticks(start: datetime, end: datetime, count: int = 5) -> list[datetime]:
    span = end - start
    return [start + span * i / (count - 1) for i in range(count)]


def date_label(moment: datetime, span: timedelta) -> str:
    local = timezone.localtime(moment)
    if span <= timedelta(days=2):
        return local.strftime("%H:%M")
    if span <= timedelta(days=400):
        return local.strftime("%d.%m")
    return local.strftime("%m.%Y")


def _step_path(points, x_of, y_of, end: datetime) -> str:
    parts: list[str] = []
    drawing = False
    for point in points:
        x = _f(x_of(point.at))
        if point.price is None:
            if drawing:
                parts.append(f"H{x}")  # the price held until it disappeared
            drawing = False
            continue
        y = _f(y_of(float(point.price)))
        parts.append(f"H{x}V{y}" if drawing else f"M{x} {y}")
        drawing = True
    if drawing:
        parts.append(f"H{_f(x_of(end))}")
    return "".join(parts)


def _out_of_stock_bands(points, x_of, end: datetime) -> list[Band]:
    bands = []
    for index, point in enumerate(points):
        if point.available is not False:
            continue
        until = points[index + 1].at if index + 1 < len(points) else end
        x0, x1 = x_of(point.at), x_of(until)
        bands.append(Band(_f(x0), _f(max(x1 - x0, 2.0))))
    return bands


def _markers(
    points,
    x_of,
    y_of,
    end: datetime,
    currency: str,
    *,
    top: float,
    bottom: float,
) -> list[Marker]:
    """Label only what matters: the current price, and the lowest and highest ones."""
    priced = [p for p in points if p.price is not None]
    last = priced[-1]
    markers = []
    end_x = x_of(end) if points[-1].price is not None else x_of(last.at)
    last_y = y_of(float(last.price))
    markers.append(
        Marker(
            _f(end_x),
            _f(last_y),
            money(last.price, currency),
            _f(end_x + 10),
            _f(last_y + 4),
            "start",
        )
    )
    if len({p.price for p in priced}) < 2:
        return markers
    lowest = min(priced, key=lambda p: (p.price, p.at))
    highest = max(priced, key=lambda p: (p.price, -p.at.timestamp()))
    for point, prefer_below in ((lowest, True), (highest, False)):
        if point.price == last.price:
            continue  # the end label already shows it
        x, y = x_of(point.at), y_of(float(point.price))
        # Keep the label inside the plot: flip it when it would hit an axis.
        below = y + 18 <= bottom - 4 if prefer_below else y - 14 < top
        label_y = y + 18 if below else y - 10
        markers.append(
            Marker(_f(x), _f(y), money(point.price, currency), _f(x), _f(label_y), "middle")
        )
    return markers


def _f(value: float) -> str:
    return f"{value:.1f}"
