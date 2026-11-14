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
DAMODARAN_COUNTRY_CURRENT_PROFILE = "damodaran-country-erp-tax-xlsx-v2"
DAMODARAN_CAPITAL_PROFILE = "damodaran-us-industry-capital-xls-v1"
_DATASET_PROFILES = {
    "/~adamodar/pc/datasets/betas.xls": DAMODARAN_BETA_PROFILE,
    "/~adamodar/pc/datasets/wacc.xls": DAMODARAN_CAPITAL_PROFILE,
    "/~adamodar/pc/datasets/ctryprem.xlsx": DAMODARAN_COUNTRY_CURRENT_PROFILE,
}
INDUSTRY_CAPITAL_COLUMNS: dict[ReferenceMetric, tuple[str, str]] = {
    "industry.equity_beta": ("C", "0.00"),
    "industry.pre_tax_cost_of_debt": ("G", "0.00%"),
    "industry.debt_weight": ("J", "0.00%"),
    "industry.equity_weight": ("E", "0.00%"),
}


def damodaran_reference_profile(uri: str) -> str:
    """Recognize maintained datasets; a URI never establishes publication time."""
    parsed = urlsplit(uri)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "pages.stern.nyu.edu"
        or parsed.query
        or parsed.fragment
    ):
        raise SnapshotError("SOURCE_QUERY_INVALID", "invalid Damodaran reference URI")
    if parsed.path in _DATASET_PROFILES:
        return _DATASET_PROFILES[parsed.path]
    if re.fullmatch(r"/~adamodar/pc/archives/betas[0-9]{2}\.xls", parsed.path):
        return DAMODARAN_BETA_PROFILE
    if re.fullmatch(r"/~adamodar/pc/archives/ctryprem[0-9]{2}\.xlsx", parsed.path):
        return DAMODARAN_COUNTRY_PROFILE
    if re.fullmatch(r"/~adamodar/pc/archives/wacc[0-9]{2}\.xls", parsed.path):
        return DAMODARAN_CAPITAL_PROFILE
    raise SnapshotError(
        "SOURCE_QUERY_INVALID", "unsupported Damodaran reference dataset"
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


def _country_current_context(
    sheet: ReferenceSheet, digest: str
) -> tuple[ReferenceContextV1, ...]:
    for reference, label in (
        ("A3", "Enter the current risk premium for a mature equity market"),
        ("A4", "Enter the current risk premium for the US ="),
        (
            "A5",
            "Do you want to adjust the country default spread for the additional volatility of the equity market to get to a country premium?",
        ),
        (
            "A6",
            "If yes, enter the multiplier to use on the default spread (See worksheet for volatility numbers for selected emerging markets)",
        ),
        ("E5", "Yes"),
    ):
        _expect(sheet, reference, label)
    context: list[ReferenceContextV1] = []
    for name, reference, numeric in (
        ("mature_market_erp", "E3", True),
        ("us_implied_erp", "E4", True),
        ("country_spread_adjustment", "E5", False),
        ("equity_volatility_multiplier", "E6", True),
        ("mature_market_method", "F3", False),
        ("us_erp_method", "F4", False),
        ("source_update_annotation", "C2", False),
    ):
        cell = sheet.cell(reference)
        if reference == "C2" and cell.kind == "empty":
            continue
        if numeric:
            value = cell.number()
            expected_format = "0.00" if reference == "E6" else "0.00%"
            if cell.number_format != expected_format or (
                value <= 0 if reference == "E6" else not 0 <= value < 1
            ):
                raise ValueError("reference methodology rate or format is invalid")
        elif cell.kind != "text" or not cell.raw.strip():
            raise ValueError("reference methodology text is missing")
        context.append(
            ReferenceContextV1(
                name=name,
                raw_value=cell.raw,
                numeric_encoding="decimal_text" if numeric else "text",
                number_format=cell.number_format,
                locator=f"ERPs by country!{reference}",
                source_sha256=digest,
            )
        )
    return tuple(context)


def _country_table(
    raw: bytes, metric: ReferenceMetric, digest: str, *, revised: bool = False
) -> tuple[date, tuple[ReferenceRowV1, ...], tuple[ReferenceContextV1, ...]]:
    erp = read_reference_xlsx(raw, "ERPs by country")
    _expect(erp, "A1", "Country and Equity Risk Premiums")
    _expect(erp, "A2", "Date of update:")
    header = 8 if revised else 7
    for column, label in (
        ("A", "Country"),
        ("D", "Rating-based Default Spread"),
        ("E", "Total Equity Risk Premium"),
        ("F", "Country Risk Premium"),
        ("H", "Total Equity Risk Premium2"),
    ):
        _expect(erp, f"{column}{header}", label)
    updated = erp.updated_on("B2")
    context = _country_current_context(erp, digest) if revised else ()
    if metric == "country.equity_risk_premium":
        name, sheet, start, column = "ERPs by country", erp, header + 1, "E"
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
        context += (
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
    rows = _industry_rows(sheet, digest, start=11, column="F", number_format="0.00")
    return sheet.updated_on("B1"), rows, context


def _industry_rows(
    sheet: ReferenceSheet,
    digest: str,
    *,
    start: int,
    column: str,
    number_format: str,
) -> tuple[ReferenceRowV1, ...]:
    rows: list[ReferenceRowV1] = []
    ended = False
    aggregates = {"Total Market", "Total Market (without financials)"}
    seen_aggregates: set[str] = set()
    for row in range(start, 1025):
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
                sheet_name="Industry Averages",
                row=row,
                column=column,
                kind="aggregate" if aggregate else "industry",
                source_hash=digest,
                expected_format=number_format,
            )
        )
    if seen_aggregates != aggregates:
        raise ValueError("reference market aggregates are incomplete")
    return tuple(rows)


def _capital_table(
    raw: bytes, metric: ReferenceMetric, digest: str
) -> tuple[date, tuple[ReferenceRowV1, ...], tuple[ReferenceContextV1, ...]]:
    name = "Industry Averages"
    sheet = read_reference_xls(raw, name)
    for reference, text in (
        ("A1", "Date updated:"),
        ("B3", "Cost of equity and capital (updateable)"),
        ("F3", "US companies"),
        ("A9", "Long Term Treasury bond rate ="),
        ("A10", "Risk Premium to Use for Equity ="),
        ("A11", "Global Default Spread to add to cost of debt ="),
        ("A12", "Do you want to use the marginal tax rate for cost of debt?"),
        ("A13", "If yes, enter the marginal tax rate to use"),
        (
            "A15",
            "These costs of capital are in US$. To convert to a different currency, please enter",
        ),
        ("A19", "Industry Name"),
        ("B19", "Number of Firms"),
        ("C19", "Beta"),
        ("D19", "Cost of Equity"),
        ("E19", "E/(D+E)"),
        ("F19", "Std Dev in Stock"),
        ("G19", "Cost of Debt"),
        ("H19", "Tax Rate"),
        ("I19", "After-tax Cost of Debt"),
        ("J19", "D/(D+E)"),
        ("K19", "Cost of Capital"),
        ("L19", "Cost of Capital (Local Currency)"),
    ):
        _expect(sheet, reference, text)
    definitions = read_reference_xls(raw, "Variables & FAQ")
    for reference, text in (
        ("A5", "Beta"),
        ("B5", "Average regression beta across companies in the group."),
        ("A7", "D/(D+E)"),
        (
            "B7",
            "Total Debt (including lease debt)/ (Total Debt (including lease debt)+ Market Cap), "
            "aggregated across all firms in group, with all numbers other than market cap coming "
            "from most recent balance sheet; market cap is as of last day of the most recent year.",
        ),
        ("A8", "Cost of debt"),
        (
            "B8",
            "Pre-tax cost of borrowing for sector, estimated based upon the standard deviation of equity.",
        ),
    ):
        _expect(definitions, reference, text)
    context = tuple(
        ReferenceContextV1(
            name=key,
            raw_value=table.cell(cell).raw,
            numeric_encoding="binary64" if encoding == "binary64" else "text",
            number_format=table.cell(cell).number_format,
            locator=f"{table_name}!{cell}",
            source_sha256=digest,
        )
        for key, table, table_name, cell, encoding in (
            ("beta_method", definitions, "Variables & FAQ", "B5", "text"),
            ("capital_weight_method", definitions, "Variables & FAQ", "B7", "text"),
            ("debt_cost_method", definitions, "Variables & FAQ", "B8", "text"),
            ("currency_basis", sheet, name, "A15", "text"),
            ("reference_risk_free", sheet, name, "D9", "binary64"),
            ("reference_erp", sheet, name, "D10", "binary64"),
            ("global_default_spread", sheet, name, "D11", "binary64"),
            ("tax_basis", sheet, name, "F12", "text"),
            ("reference_marginal_tax", sheet, name, "F13", "binary64"),
        )
    )
    for cell in ("D9", "D10", "D11", "F13"):
        if not 0 <= sheet.cell(cell).number() < 1:
            raise ValueError("industry capital methodology rate is outside its domain")
    if sheet.cell("F12").raw.strip() != "Yes":
        raise ValueError("industry capital tax methodology changed")
    column, number_format = INDUSTRY_CAPITAL_COLUMNS[metric]
    rows = _industry_rows(
        sheet, digest, start=20, column=column, number_format=number_format
    )
    return sheet.updated_on("B1"), rows, context


class DamodaranReferenceProvider:
    """Adapt original public tables; source capture time bounds availability."""

    provider_id = "damodaran-public-aggregates"

    def supports(self, metric: ReferenceMetric) -> bool:
        return (
            metric
            in {
                "industry.unlevered_beta",
                "country.equity_risk_premium",
                "country.tax_rate",
            }
            or metric in INDUSTRY_CAPITAL_COLUMNS
        )

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
            capital = metric in INDUSTRY_CAPITAL_COLUMNS
            expected_profile = (
                DAMODARAN_CAPITAL_PROFILE
                if capital
                else DAMODARAN_BETA_PROFILE
                if beta
                else DAMODARAN_COUNTRY_CURRENT_PROFILE
                if profile == DAMODARAN_COUNTRY_CURRENT_PROFILE
                else DAMODARAN_COUNTRY_PROFILE
            )
            if (
                source.source_id != DAMODARAN_SOURCE
                or source.source_version != profile
                or source.terms_reference != DAMODARAN_TERMS
                or profile != expected_profile
                or source.captured_at.tzinfo is None
                or source.captured_at.utcoffset() is None
            ):
                raise ValueError(
                    "reference source profile differs from the requested metric"
                )
            digest = hashlib.sha256(source.content).hexdigest()
            updated, rows, context = (
                _capital_table(source.content, metric, digest)
                if capital
                else _beta_table(source.content, digest)
                if beta
                else _country_table(
                    source.content,
                    metric,
                    digest,
                    revised=profile == DAMODARAN_COUNTRY_CURRENT_PROFILE,
                )
            )
            captured = source.captured_at.astimezone(UTC)
            return MarketReferenceVintageV1.build(
                metric=metric,
                population="us-companies" if beta or capital else "countries",
                unit="multiple"
                if metric in {"industry.unlevered_beta", "industry.equity_beta"}
                else "fraction",
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
