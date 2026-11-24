"""CSV and Excel exports of the product list (with the dashboard's filters applied)."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from io import BytesIO
from typing import Any

from django.db.models import QuerySet
from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from apps.catalog.models import Product

COLUMNS = (
    ("ID", 8),
    ("Товар", 60),
    ("Магазин", 18),
    ("Ціна", 12),
    ("Стара ціна", 12),
    ("Знижка, %", 11),
    ("Валюта", 8),
    ("Наявність", 14),
    ("Перевірено", 18),
    ("Посилання", 50),
)
STOCK = {True: "в наявності", False: "немає", None: "невідомо"}
# Text that a spreadsheet would run as a formula (CSV / formula injection, OWASP).
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def csv_response(products: QuerySet[Product]) -> HttpResponse:
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{_filename("csv")}"'
    response.write("﻿")  # BOM: Excel then opens UTF-8 Cyrillic correctly
    writer = csv.writer(response)
    writer.writerow([name for name, _ in COLUMNS])
    for row in product_rows(products):
        writer.writerow(["" if value is None else value for value in row])
    return response


def xlsx_response(products: QuerySet[Product]) -> HttpResponse:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Товари"
    sheet.append([name for name, _ in COLUMNS])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="17233A")
        cell.fill = PatternFill("solid", fgColor="FFD21F")
        cell.alignment = Alignment(vertical="center")
    for row in product_rows(products):
        sheet.append(row)
        url_cell = sheet.cell(row=sheet.max_row, column=len(COLUMNS))
        url_cell.hyperlink = url_cell.value
    for index, (_, width) in enumerate(COLUMNS, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for column in ("D", "E"):
        for cell in sheet[column][1:]:
            cell.number_format = "#,##0.00"
    for cell in sheet["I"][1:]:
        cell.number_format = "dd.mm.yyyy hh:mm"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    buffer = BytesIO()
    workbook.save(buffer)
    response = HttpResponse(buffer.getvalue(), content_type=XLSX_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{_filename("xlsx")}"'
    return response


def product_rows(products: QuerySet[Product]) -> Iterator[list[Any]]:
    for product in products.iterator(chunk_size=1000):
        checked = product.last_checked_at
        yield [
            product.pk,
            safe_text(product.title),
            safe_text(product.shop.name),
            product.price,
            product.old_price,
            product.discount_percent,
            product.currency,
            STOCK[product.is_available],
            timezone.localtime(checked).replace(tzinfo=None) if checked else None,
            product.url,
        ]


def safe_text(value: str) -> str:
    return f"'{value}" if value.startswith(FORMULA_PREFIXES) else value


def _filename(extension: str) -> str:
    return f"pricewatch-{timezone.localdate():%Y-%m-%d}.{extension}"
