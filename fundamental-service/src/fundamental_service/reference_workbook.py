"""Bounded, non-executing workbook cells for published reference tables."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Literal
from xml.etree import ElementTree

import xlrd

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_OFFICE = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_MAX_BYTES = 10 * 1024 * 1024
_MAX_ROWS = 1024
_MAX_COLS = 32


@dataclass(frozen=True)
class ReferenceCell:
    kind: Literal["text", "binary64", "decimal_text", "empty", "error"]
    raw: str
    number_format: str = "General"
    formula: str | None = None
    formula_attributes: tuple[tuple[str, str], ...] = ()

    def number(self) -> Decimal:
        if self.kind == "binary64":
            value = Decimal.from_float(float.fromhex(self.raw))
        elif self.kind == "decimal_text":
            value = Decimal(self.raw)
        else:
            raise ValueError("reference cell is not numeric")
        if not value.is_finite():
            raise ValueError("reference number is not finite")
        return value


@dataclass(frozen=True)
class ReferenceSheet:
    cells: dict[str, ReferenceCell]
    date_1904: bool

    def cell(self, reference: str) -> ReferenceCell:
        return self.cells.get(reference, ReferenceCell("empty", ""))

    def updated_on(self, reference: str) -> date:
        serial = self.cell(reference).number()
        if serial != serial.to_integral_value() or not 61 <= serial <= 100000:
            raise ValueError("reference update date must be an unambiguous whole date")
        origin = date(1904, 1, 1) if self.date_1904 else date(1899, 12, 30)
        return origin + timedelta(days=int(serial))


def _coordinate(reference: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", reference)
    if match is None:
        raise ValueError("reference cell coordinate is invalid")
    column = 0
    for char in match[1]:
        column = column * 26 + ord(char) - ord("A") + 1
    row = int(match[2])
    if column > _MAX_COLS or row > _MAX_ROWS:
        raise ValueError("reference sheet exceeds its bounded profile")
    return row, column


def _xml(raw: bytes) -> ElementTree.Element:
    text = raw.decode("utf-8-sig")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("reference XML declarations are forbidden")
    return ElementTree.fromstring(text)


def read_reference_xlsx(raw: bytes, sheet_name: str) -> ReferenceSheet:
    """Preserve OOXML numeric lexemes and formats; never evaluate formulas."""
    if not raw or len(raw) > _MAX_BYTES:
        raise ValueError("reference workbook size exceeds its bounded profile")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        names = [x.filename for x in members]
        if (
            len(names) > 256
            or len(set(names)) != len(names)
            or sum(x.file_size for x in members) > 50 * 1024 * 1024
            or any(
                x.flag_bits & 1
                or x.filename.startswith("/")
                or ".." in PurePosixPath(x.filename).parts
                for x in members
            )
        ):
            raise ValueError("reference workbook archive is unsafe or ambiguous")
        workbook = _xml(archive.read("xl/workbook.xml"))
        properties = workbook.find(f"{_NS}workbookPr")
        epoch = "0" if properties is None else properties.get("date1904", "0")
        if epoch not in {"0", "1", "false", "true"}:
            raise ValueError("reference workbook date system is unknown")
        sheets = workbook.findall(f"{_NS}sheets/{_NS}sheet")
        if len({x.get("name") for x in sheets}) != len(sheets):
            raise ValueError("reference workbook repeats a sheet name")
        selected = [x for x in sheets if x.get("name") == sheet_name]
        if len(selected) != 1:
            raise ValueError("reference sheet is missing or ambiguous")
        links = _xml(archive.read("xl/_rels/workbook.xml.rels")).findall(
            f"{_REL}Relationship"
        )
        if len({x.get("Id") for x in links}) != len(links):
            raise ValueError("reference workbook repeats a relationship identity")
        targets = [
            x
            for x in links
            if x.get("Id") == selected[0].get(f"{_OFFICE}id")
            and x.get("Type") == f"{_OFFICE[1:-1]}/worksheet"
            and x.get("TargetMode") != "External"
        ]
        if len(targets) != 1:
            raise ValueError("reference sheet relationship is invalid")
        target = PurePosixPath(targets[0].attrib["Target"])
        if target.is_absolute() or ".." in target.parts:
            raise ValueError("reference sheet path is invalid")
        strings: list[str] = []
        if "xl/sharedStrings.xml" in names:
            strings = [
                "".join(t.text or "" for t in item.iter(f"{_NS}t"))
                for item in _xml(archive.read("xl/sharedStrings.xml")).findall(
                    f"{_NS}si"
                )
            ]
        styles = _xml(archive.read("xl/styles.xml"))
        formats = {
            0: "General",
            1: "0",
            2: "0.00",
            9: "0%",
            10: "0.00%",
            14: "mm-dd-yy",
        }
        custom = styles.findall(f"{_NS}numFmts/{_NS}numFmt")
        ids = [int(x.attrib["numFmtId"]) for x in custom]
        if len(set(ids)) != len(ids) or set(ids) & set(formats):
            raise ValueError("reference number format identity is ambiguous")
        formats.update(
            {int(x.attrib["numFmtId"]): x.attrib["formatCode"] for x in custom}
        )
        style_ids = [
            int(x.get("numFmtId", "0")) for x in styles.findall(f"{_NS}cellXfs/{_NS}xf")
        ]
        cells: dict[str, ReferenceCell] = {}
        worksheet = _xml(archive.read(str(PurePosixPath("xl") / target)))
        row_ids: set[int] = set()
        for row in worksheet.findall(f"{_NS}sheetData/{_NS}row"):
            row_id = int(row.attrib["r"])
            if row_id in row_ids or not 1 <= row_id <= _MAX_ROWS:
                raise ValueError("reference row identity is repeated or out of bounds")
            row_ids.add(row_id)
            for cell in row.findall(f"{_NS}c"):
                reference = cell.attrib["r"]
                if _coordinate(reference)[0] != row_id or reference in cells:
                    raise ValueError(
                        "reference cell identity is repeated or inconsistent"
                    )
                style = int(cell.get("s", "0"))
                if not 0 <= style < len(style_ids):
                    raise ValueError("reference cell style is invalid")
                # Unselected decorative cells may use unrelated built-in formats.
                number_format = formats.get(
                    style_ids[style], f"builtin:{style_ids[style]}"
                )
                values = cell.findall(f"{_NS}v")
                if len(values) > 1:
                    raise ValueError("reference cell repeats a cached value")
                text = "" if not values else values[0].text or ""
                kind = cell.get("t", "n")
                if kind == "s":
                    index = int(text)
                    if not 0 <= index < len(strings):
                        raise ValueError("reference shared string index is invalid")
                    result = ReferenceCell("text", strings[index], number_format)
                elif kind == "inlineStr":
                    result = ReferenceCell(
                        "text",
                        "".join(x.text or "" for x in cell.iter(f"{_NS}t")),
                        number_format,
                    )
                elif kind == "str":
                    result = ReferenceCell("text", text, number_format)
                elif kind == "e":
                    result = ReferenceCell("error", text, number_format)
                elif kind == "n":
                    result = ReferenceCell(
                        "decimal_text" if text else "empty", text, number_format
                    )
                else:
                    raise ValueError("reference cell has an unsupported type")
                formulas = cell.findall(f"{_NS}f")
                if len(formulas) > 1:
                    raise ValueError("reference cell repeats its formula")
                if formulas:
                    result = replace(
                        result,
                        formula=formulas[0].text or "",
                        formula_attributes=tuple(sorted(formulas[0].attrib.items())),
                    )
                cells[reference] = result
    return ReferenceSheet(cells, epoch in {"1", "true"})


def read_reference_xls(raw: bytes, sheet_name: str) -> ReferenceSheet:
    """Read retained BIFF cached values, preserving exact binary64 and formats."""
    if (
        not raw
        or len(raw) > _MAX_BYTES
        or not raw.startswith(bytes.fromhex("d0cf11e0a1b11ae1"))
    ):
        raise ValueError("reference XLS size or signature is invalid")
    book = xlrd.open_workbook(file_contents=raw, on_demand=True, formatting_info=True)
    try:
        names = book.sheet_names()
        if len(names) > 32 or len(set(names)) != len(names) or sheet_name not in names:
            raise ValueError("reference XLS sheet identity is invalid")
        sheet = book.sheet_by_name(sheet_name)
        if (
            sheet.nrows > _MAX_ROWS
            or sheet.ncols > _MAX_COLS
            or book.datemode not in {0, 1}
        ):
            raise ValueError("reference XLS exceeds its bounded profile")
        cells: dict[str, ReferenceCell] = {}
        for row in range(sheet.nrows):
            for column in range(sheet.ncols):
                cell = sheet.cell(row, column)
                fmt = book.format_map[book.xf_list[cell.xf_index].format_key].format_str
                # The profile is bounded to A:AF.
                name = (
                    chr(ord("A") + column)
                    if column < 26
                    else "A" + chr(ord("A") + column - 26)
                ) + str(row + 1)
                if cell.ctype in {xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK}:
                    result = ReferenceCell("empty", "", fmt)
                elif cell.ctype in {xlrd.XL_CELL_NUMBER, xlrd.XL_CELL_DATE}:
                    if not isinstance(cell.value, float):
                        raise ValueError("reference XLS number is not binary64")
                    result = ReferenceCell("binary64", cell.value.hex(), fmt)
                elif cell.ctype == xlrd.XL_CELL_TEXT and isinstance(cell.value, str):
                    result = ReferenceCell("text", cell.value, fmt)
                elif cell.ctype == xlrd.XL_CELL_ERROR:
                    result = ReferenceCell("error", str(cell.value), fmt)
                else:
                    raise ValueError("reference XLS cell has an unsupported type")
                cells[name] = result
        return ReferenceSheet(cells, book.datemode == 1)
    finally:
        book.release_resources()
