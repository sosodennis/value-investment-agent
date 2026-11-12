"""Pure adapters for retained public aggregate Damodaran reference workbooks."""

from __future__ import annotations

import hashlib
import re
import struct
import zipfile
from datetime import UTC, date
from decimal import DecimalException
from typing import Literal
from urllib.parse import urlsplit
from xml.etree import ElementTree

from xlrd.biffh import XLRDError
from xlrd.compdoc import CompDocError

from .market_reference import (
    MarketReferenceVintageV1,
    ReferenceContextV1,
    ReferenceMetric,
    ReferenceRowV1,
)
from .reference_workbook import (
    ReferenceSheet,
    read_reference_xls,
    read_reference_xlsx,
)
from .snapshots import SnapshotError
from .source_evidence import RetainedSourceV1, SourceArtifactV1

DAMODARAN_SOURCE = "damodaran-reference"
DAMODARAN_TERMS = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/"
DAMODARAN_BETA_PROFILE = "damodaran-us-unlevered-beta-xls-v1"
DAMODARAN_COUNTRY_PROFILE = "damodaran-country-erp-tax-xlsx-v1"


def damodaran_reference_profile(uri: str) -> str:
    """Recognize a canonical archive URI; filenames never establish publication time."""
    parsed = urlsplit(uri)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "pages.stern.nyu.edu"
        or parsed.query
        or parsed.fragment
    ):
        raise SnapshotError("SOURCE_QUERY_INVALID", "invalid Damodaran archive URI")
    if re.fullmatch(r"/~adamodar/pc/archives/betas[0-9]{2}\.xls", parsed.path):
        return DAMODARAN_BETA_PROFILE
    if re.fullmatch(r"/~adamodar/pc/archives/ctryprem[0-9]{2}\.xlsx", parsed.path):
        return DAMODARAN_COUNTRY_PROFILE
    raise SnapshotError(
        "SOURCE_QUERY_INVALID", "unsupported Damodaran reference archive"
    )


def _expect(sheet: ReferenceSheet, reference: str, text: str) -> None:
    cell = sheet.cell(reference)
    if cell.kind != "text" or cell.raw.strip() != text:
        raise ValueError(f"reference table identity differs at {reference}")


def _row(
    sheet: ReferenceSheet,
    *,
    sheet_name: str,
    row: int,
    column: str,
    kind: Literal["country", "industry", "aggregate"],
    source_hash: str,
    expected_format: str,
) -> ReferenceRowV1:
    subject = sheet.cell(f"A{row}")
    if subject.kind != "text" or not subject.raw.strip():
        raise ValueError("reference table subject is missing or not text")
    cell = sheet.cell(f"{column}{row}")
    common = {
        "subject": subject.raw.strip(),
        "subject_kind": kind,
        "locator": f"{sheet_name}!{column}{row}",
        "source_sha256": source_hash,
        "raw_value": cell.raw,
        "number_format": cell.number_format,
        "source_formula": cell.formula,
        "source_formula_attributes": cell.formula_attributes,
        "value_basis": (
            "published_biff_cache"
            if sheet_name == "Industry Averages"
            else "published_ooxml_cache"
            if cell.formula is not None
            else "published_cell"
        ),
    }
    if cell.kind in {"binary64", "decimal_text"}:
        if cell.number_format != expected_format:
            raise ValueError("reference numeric display precision changed")
        return ReferenceRowV1.model_validate(
            {
                **common,
                "value": cell.number(),
                "numeric_encoding": cell.kind,
                "missing_reason": None,
            }
        )
    reasons = {"empty": "empty_cell", "error": "cell_error"}
    if cell.kind == "text" and cell.raw.strip() in {
        "NA",
        "N/A",
        "n/a",
        "-",
        "#N/A",
    }:
        reason = "source_marker"
    elif cell.kind in reasons:
        reason = reasons[cell.kind]
        if cell.kind == "empty" and cell.formula is not None:
            reason = "formula_cache_missing"
    else:
        raise ValueError("reference cell has an unknown nonnumeric value")
    return ReferenceRowV1.model_validate(
        {
            **common,
            "value": None,
            "numeric_encoding": "missing",
            "missing_reason": reason,
        }
    )


def _country_table(
    raw: bytes, metric: ReferenceMetric, digest: str
) -> tuple[date, tuple[ReferenceRowV1, ...], tuple[ReferenceContextV1, ...]]:
    erp = read_reference_xlsx(raw, "ERPs by country")
    _expect(erp, "A1", "Country and Equity Risk Premiums")
    _expect(erp, "A2", "Date of update:")
    _expect(erp, "A7", "Country")
    _expect(erp, "D7", "Rating-based Default Spread")
    _expect(erp, "E7", "Total Equity Risk Premium")
    _expect(erp, "F7", "Country Risk Premium")
    _expect(erp, "H7", "Total Equity Risk Premium2")
    updated = erp.updated_on("B2")
    context: tuple[ReferenceContextV1, ...] = ()
    if metric == "country.equity_risk_premium":
        name, sheet, start, column = "ERPs by country", erp, 8, "E"
        markers = [
            row
            for row in range(start, 1024)
            if sheet.cell(f"A{row}").raw.strip()
            == "Frontier Markets (no sovereign ratings)"
        ]
        if len(markers) != 1:
            raise ValueError("reference ERP table end marker is missing or ambiguous")
        end = markers[0]
        _expect(sheet, f"A{end + 1}", "Country")
        _expect(sheet, f"B{end + 1}", "PRS Composite Risk Score")
    else:
        name = "Country Tax Rates"
        sheet = read_reference_xlsx(raw, name)
        _expect(sheet, "A1", "Country")
        _expect(sheet, "B1", "Tax Rate")
        note = sheet.cell("C1")
        if (
            note.kind != "text"
            or re.fullmatch(r"Looked up for [0-9]{4}", note.raw) is None
        ):
            raise ValueError("reference tax lookup period is unknown")
        context = (
            ReferenceContextV1(
                name="tax_lookup_period",
                raw_value=note.raw,
                numeric_encoding="text",
                number_format=note.number_format,
                locator=f"{name}!C1",
                source_sha256=digest,
            ),
        )
        start, column = 2, "B"
        end = next(
            (
                row
                for row in range(start, 1025)
                if sheet.cell(f"A{row}").kind == "empty"
            ),
            1025,
        )
        if any(sheet.cell(f"A{row}").kind != "empty" for row in range(end, 1025)):
            raise ValueError("reference tax country table has a gap or unexpected tail")
    rows: list[ReferenceRowV1] = []
    for row in range(start, end):
        rows.append(
            _row(
                sheet,
                sheet_name=name,
                row=row,
                column=column,
                kind="country",
                source_hash=digest,
                expected_format="0.00%",
            )
        )
    if metric == "country.equity_risk_premium":
        rows.append(
            _row(
                erp,
                sheet_name=name,
                row=end,
                column=column,
                kind="aggregate",
                source_hash=digest,
                expected_format="0.00%",
            )
        )
    return updated, tuple(rows), context


def _beta_table(
    raw: bytes, digest: str
) -> tuple[date, tuple[ReferenceRowV1, ...], tuple[ReferenceContextV1, ...]]:
    name = "Industry Averages"
    sheet = read_reference_xls(raw, name)
    for reference, text in (
        ("A1", "Date updated:"),
        ("B3", "Beta, Unlevered beta and other risk measures"),
        ("F3", "US companies"),
        ("F8", "Marginal"),
        ("A10", "Industry Name"),
        ("B10", "Number of firms"),
        ("C10", "Beta"),
        ("D10", "D/E Ratio"),
        ("E10", "Effective Tax rate"),
        ("F10", "Unlevered beta"),
        ("H10", "Unlevered beta corrected for cash"),
    ):
        _expect(sheet, reference, text)
    tax = sheet.cell("F9").number()
    if not 0 <= tax < 1:
        raise ValueError("reference marginal tax context is invalid")
    context = tuple(
        ReferenceContextV1(
            name=key,
            raw_value=sheet.cell(cell).raw,
            numeric_encoding="text" if cell == "F8" else "binary64",
            number_format=sheet.cell(cell).number_format,
            locator=f"{name}!{cell}",
            source_sha256=digest,
        )
        for key, cell in (("tax_basis", "F8"), ("marginal_tax_raw_binary64", "F9"))
    )
    rows: list[ReferenceRowV1] = []
    ended = False
    aggregates = {"Total Market", "Total Market (without financials)"}
    seen_aggregates: set[str] = set()
    for row in range(11, 1025):
        subject = sheet.cell(f"A{row}")
        if subject.kind == "empty" or (
            subject.kind == "text" and not subject.raw.strip()
        ):
            ended = True
            continue
        if ended:
            raise ValueError(
                "reference industry table contains a gap or unexpected tail"
            )
        label = subject.raw.strip()
        aggregate = label in aggregates
        if seen_aggregates and not aggregate:
            raise ValueError("industry row follows reference market aggregates")
        if aggregate:
            seen_aggregates.add(label)
        rows.append(
            _row(
                sheet,
                sheet_name=name,
                row=row,
                column="F",
                kind="aggregate" if aggregate else "industry",
                source_hash=digest,
                expected_format="0.00",
            )
        )
    if seen_aggregates != aggregates:
        raise ValueError("reference market aggregates are incomplete")
    return sheet.updated_on("B1"), tuple(rows), context


class DamodaranReferenceProvider:
    """Adapt original public tables; source capture time bounds availability."""

    provider_id = "damodaran-public-aggregates"

    def supports(self, metric: ReferenceMetric) -> bool:
        return metric in {
            "industry.unlevered_beta",
            "country.equity_risk_premium",
            "country.tax_rate",
        }

    def reproduce_vintage(
        self, *, metric: ReferenceMetric, sources: tuple[RetainedSourceV1, ...]
    ) -> MarketReferenceVintageV1:
        try:
            if not self.supports(metric) or len(sources) != 1:
                raise ValueError(
                    "reference metric requires exactly one original workbook"
                )
            source = sources[0]
            profile = damodaran_reference_profile(source.uri)
            beta = metric == "industry.unlevered_beta"
            if (
                source.source_id != DAMODARAN_SOURCE
                or source.source_version != profile
                or source.terms_reference != DAMODARAN_TERMS
                or profile
                != (DAMODARAN_BETA_PROFILE if beta else DAMODARAN_COUNTRY_PROFILE)
                or source.captured_at.tzinfo is None
                or source.captured_at.utcoffset() is None
            ):
                raise ValueError(
                    "reference source profile differs from the requested metric"
                )
            digest = hashlib.sha256(source.content).hexdigest()
            updated, rows, context = (
                _beta_table(source.content, digest)
                if beta
                else _country_table(source.content, metric, digest)
            )
            captured = source.captured_at.astimezone(UTC)
            return MarketReferenceVintageV1.build(
                metric=metric,
                population="us-companies" if beta else "countries",
                unit="multiple" if beta else "fraction",
                provider_id=self.provider_id,
                source_version=source.source_version,
                source_updated_on=updated,
                available_at=captured,
                captured_at=captured,
                artifacts=(
                    SourceArtifactV1(
                        source_id=source.source_id,
                        uri=source.uri,
                        source_version=source.source_version,
                        terms_reference=source.terms_reference,
                        content_sha256=digest,
                        captured_at=captured,
                    ),
                ),
                rows=rows,
                context=context,
            )
        except (
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            UnicodeError,
            DecimalException,
            ElementTree.ParseError,
            zipfile.BadZipFile,
            XLRDError,
            CompDocError,
            struct.error,
        ) as error:
            raise SnapshotError(
                "REFERENCE_SOURCE_INVALID",
                "retained workbook does not reproduce the reference profile",
            ) from error
