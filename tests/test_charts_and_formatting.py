from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.catalog.formatting import money, percent_change
from apps.dashboard.charts import (
    ChartPoint,
    axis_label,
    build_price_chart,
    date_label,
    nice_ticks,
    sparkline_path,
)

START = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "currency", "expected"),
    [
        (Decimal("36999"), "UAH", "36 999 ₴"),
        (Decimal("719.20"), "UAH", "719,20 ₴"),
        (Decimal("1234567.5"), "UAH", "1 234 567,50 ₴"),
        (Decimal("295.99"), "USD", "$295.99"),
        (Decimal("10"), "EUR", "€10"),
        (Decimal("10"), "PLN", "10 PLN"),
        (None, "UAH", "—"),
    ],
)
def test_money(value: Decimal | None, currency: str, expected: str) -> None:
    assert money(value, currency) == expected


def test_percent_change() -> None:
    assert percent_change(Decimal(500), Decimal(399)) == -20
    assert percent_change(Decimal(100), Decimal(107)) == 7
    assert percent_change(None, Decimal(1)) is None
    assert percent_change(Decimal(0), Decimal(1)) is None


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [
        (6049, 8499, [6000.0, 7000.0, 8000.0, 9000.0]),
        (399, 399, [370.0, 380.0, 390.0, 400.0, 410.0, 420.0]),  # a flat price gets ±5%
        (36999, 49299, [35000.0, 40000.0, 45000.0, 50000.0]),
    ],
)
def test_nice_ticks(low: float, high: float, expected: list[float]) -> None:
    assert nice_ticks(low, high) == expected


def test_axis_labels_are_compact_from_ten_thousand() -> None:
    assert axis_label(7500, top=9000) == "7 500"
    assert axis_label(36500, top=50000) == "36,5 тис."
    assert axis_label(40000, top=50000) == "40 тис."


def test_date_labels_follow_the_span() -> None:
    moment = datetime(2026, 11, 24, 9, 30, tzinfo=UTC)
    assert date_label(moment, timedelta(hours=10)).endswith(":30")
    assert date_label(moment, timedelta(days=60)) == "24.11"
    assert date_label(moment, timedelta(days=800)) == "11.2026"


def test_price_chart_steps_bands_and_labels() -> None:
    points = [
        ChartPoint(START, Decimal(1000), True),
        ChartPoint(START + timedelta(days=5), Decimal(900), True),
        ChartPoint(START + timedelta(days=10), Decimal(900), False),
        ChartPoint(START + timedelta(days=15), Decimal(1100), True),
    ]

    chart = build_price_chart(points, now=START + timedelta(days=20), width=760, height=280)

    assert chart is not None
    assert chart.line_path.startswith("M72.0 ")
    assert chart.line_path.count("M") == 1
    assert chart.line_path.endswith(f"H{chart.right:.1f}")  # the price holds until now
    assert len(chart.bands) == 1  # the sold-out stretch
    assert [m.label for m in chart.markers] == ["1 100 ₴", "900 ₴"]  # now, then the low
    assert len(chart.points) == 4
    assert chart.points[2]["stock"] == "немає в наявності"
    assert "зараз 1 100 ₴" in chart.summary


def test_missing_price_breaks_the_line_and_compact_chart_has_fewer_ticks() -> None:
    points = [
        ChartPoint(START, Decimal(10), True),
        ChartPoint(START + timedelta(days=1), None, None),
        ChartPoint(START + timedelta(days=2), Decimal(12), True),
    ]

    chart = build_price_chart(points, now=START + timedelta(days=3), width=380, height=240)

    assert chart is not None
    assert chart.line_path.count("M") == 2
    assert len(chart.x_ticks) == 3
    assert chart.points[1]["price"] == "без ціни"


def test_no_chart_without_prices() -> None:
    assert build_price_chart([ChartPoint(START, None, False)]) is None
    assert build_price_chart([]) is None


def test_sparkline() -> None:
    assert sparkline_path([Decimal(1)]) is None
    path, end_x, end_y = sparkline_path([Decimal(10), None, Decimal(8), Decimal(12)])
    assert path.startswith("M4.0 ")
    assert end_x == "68.0"
    assert end_y == "4.0"  # the highest price sits at the top
