"""Domain projection contract for valuation inputs.

This module owns domain-facing `FinancialReport` projection/coercion used by
valuation param builders. Canonical payload ownership stays in
`interface/contracts.py`.
Input mappings here are expected to already be canonicalized; this module no
longer performs extension-type inference fallback.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.agents.fundamental.domain.shared.contracts.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
    XBRLProvenance,
)

CANONICAL_EXTENSION_TYPES: tuple[str, ...] = (
    "Industrial",
    "FinancialServices",
    "RealEstate",
)


@dataclass(frozen=True)
class TraceableNamespace:
    fields: dict[str, TraceableField]

    def __getattr__(self, name: str) -> TraceableField:
        return self.fields.get(
            name, _missing_traceable_field(name, f"Missing field '{name}'")
        )


@dataclass(frozen=True)
class BaseFinancialModel(TraceableNamespace):
    pass


@dataclass(frozen=True)
class IndustrialExtension(TraceableNamespace):
    pass


@dataclass(frozen=True)
class FinancialServicesExtension(TraceableNamespace):
    pass


@dataclass(frozen=True)
class RealEstateExtension(TraceableNamespace):
    pass


@dataclass(frozen=True)
class FilingMetadata:
    form: str | None = None
    accession_number: str | None = None
    filing_date: str | None = None
    accepted_datetime: str | None = None
    period_of_report: str | None = None
    requested_fiscal_year: int | None = None
    matched_fiscal_year: int | None = None
    selection_mode: str | None = None


@dataclass(frozen=True)
class FinancialReport:
    base: BaseFinancialModel
    extension: (
        IndustrialExtension | FinancialServicesExtension | RealEstateExtension | None
    ) = None
    industry_type: str = "General"
    filing_metadata: FilingMetadata | None = None


TRACEABLE_FIELD_LABELS: dict[str, str] = {
    "ticker": "Ticker",
    "cik": "CIK",
    "company_name": "Company Name",
    "sic_code": "SIC Code",
    "fiscal_year": "Fiscal Year",
    "fiscal_period": "Fiscal Period",
    "period_end_date": "Period End Date",
    "currency": "Currency",
    "shares_outstanding": "Shares Outstanding",
    "weighted_average_shares_basic": "Weighted Average Shares Outstanding (Basic)",
    "weighted_average_shares_diluted": "Weighted Average Shares Outstanding (Diluted)",
    "total_assets": "Total Assets",
    "total_liabilities": "Total Liabilities",
    "total_equity": "Total Equity",
    "cash_and_equivalents": "Cash & Cash Equivalents",
    "current_assets": "Current Assets",
    "current_liabilities": "Current Liabilities",
    "total_debt": "Total Debt",
    "preferred_stock": "Preferred Stock",
    "total_revenue": "Total Revenue",
    "operating_income": "Operating Income (EBIT)",
    "income_before_tax": "Income Before Tax",
    "interest_expense": "Interest Expense",
    "depreciation_and_amortization": "Depreciation & Amortization",
    "share_based_compensation": "Share-Based Compensation",
    "net_income": "Net Income",
    "income_tax_expense": "Income Tax Expense",
    "ebitda": "EBITDA",
    "operating_cash_flow": "Operating Cash Flow",
    "dividends_paid": "Dividends Paid",
    "working_capital": "Working Capital",
    "working_capital_delta": "Working Capital Delta",
    "effective_tax_rate": "Effective Tax Rate",
    "interest_cost_rate": "Interest Cost Rate",
    "ebit_margin": "EBIT Margin",
    "net_margin": "Net Margin",
    "invested_capital": "Invested Capital",
    "nopat": "NOPAT",
    "roic": "ROIC",
    "reinvestment_rate": "Reinvestment Rate",
    "inventory": "Inventory",
    "accounts_receivable": "Accounts Receivable",
    "cogs": "Cost of Goods Sold (COGS)",
    "rd_expense": "R&D Expense",
    "sga_expense": "SG&A Expense",
    "selling_expense": "Selling Expense",
    "ga_expense": "G&A Expense",
    "capex": "Capital Expenditures (CapEx)",
    "loans_and_leases": "Loans and Leases",
    "deposits": "Deposits",
    "allowance_for_credit_losses": "Allowance for Credit Losses",
    "interest_income": "Interest Income",
    "provision_for_loan_losses": "Provision for Loan Losses",
    "risk_weighted_assets": "Risk-Weighted Assets",
    "tier1_capital_ratio": "Tier 1 Capital Ratio",
    "real_estate_assets": "Real Estate Assets (at cost)",
    "accumulated_depreciation": "Accumulated Depreciation",
    "gain_on_sale": "Gain on Sale of Properties",
    "ffo": "FFO (Funds From Operations)",
}


def parse_domain_financial_reports(
    reports: list[Mapping[str, object]],
) -> list[FinancialReport]:
    result: list[FinancialReport] = []
    for item in reports:
        if isinstance(item, Mapping):
            result.append(_coerce_report(item))
            continue
        raise TypeError(f"financial report item has unsupported type: {type(item)!r}")
    return result


def _coerce_report(value: Mapping[str, object]) -> FinancialReport:
    base_raw = _as_mapping(value.get("base"), "financial report.base")
    extension_raw = value.get("extension")
    extension_map = (
        _as_mapping(extension_raw, "financial report.extension")
        if extension_raw is not None
        else None
    )
    extension_type = _resolve_extension_type(
        value,
        has_extension=extension_map is not None,
    )
    filing_metadata = _coerce_filing_metadata(value.get("filing_metadata"))

    base = BaseFinancialModel(
        fields=_coerce_traceable_mapping(base_raw, context="financial report.base")
    )

    extension: (
        IndustrialExtension | FinancialServicesExtension | RealEstateExtension | None
    ) = None
    if extension_type == "Industrial":
        extension = IndustrialExtension(
            fields=_coerce_traceable_mapping(
                extension_map or {}, context="financial report.extension"
            )
        )
    elif extension_type == "FinancialServices":
        extension = FinancialServicesExtension(
            fields=_coerce_traceable_mapping(
                extension_map or {}, context="financial report.extension"
            )
        )
    elif extension_type == "RealEstate":
        extension = RealEstateExtension(
            fields=_coerce_traceable_mapping(
                extension_map or {}, context="financial report.extension"
            )
        )

    return FinancialReport(
        base=base,
        extension=extension,
        industry_type=extension_type or "General",
        filing_metadata=filing_metadata,
    )


def _as_mapping(value: object, context: str) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    raise TypeError(f"{context} must be an object")


def _resolve_extension_type(
    payload: Mapping[str, object], *, has_extension: bool
) -> str | None:
    extension_type = _parse_canonical_extension_type(
        payload.get("extension_type"), context="financial report.extension_type"
    )
    if has_extension and extension_type is None:
        raise TypeError(
            "financial report.extension requires extension_type in canonical payload"
        )
    return extension_type


def _parse_canonical_extension_type(value: object, *, context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{context} must be canonical token")
    token = value.strip()
    if token in CANONICAL_EXTENSION_TYPES:
        return token
    allowed = ", ".join(CANONICAL_EXTENSION_TYPES)
    raise TypeError(f"{context} must be canonical token ({allowed})")


def _coerce_traceable_mapping(
    mapping: Mapping[str, object], *, context: str
) -> dict[str, TraceableField]:
    output: dict[str, TraceableField] = {}
    for key, item in mapping.items():
        output[key] = _coerce_traceable_field(item, key=key, context=f"{context}.{key}")
    return output


def _coerce_filing_metadata(value: object) -> FilingMetadata | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("financial report.filing_metadata must be an object")
    return FilingMetadata(
        form=_coerce_optional_text(value.get("form")),
        accession_number=_coerce_optional_text(value.get("accession_number")),
        filing_date=_coerce_optional_text(value.get("filing_date")),
        accepted_datetime=_coerce_optional_text(value.get("accepted_datetime")),
        period_of_report=_coerce_optional_text(value.get("period_of_report")),
        requested_fiscal_year=_coerce_optional_int(value.get("requested_fiscal_year")),
        matched_fiscal_year=_coerce_optional_int(value.get("matched_fiscal_year")),
        selection_mode=_coerce_optional_text(value.get("selection_mode")),
    )


def _coerce_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized else None


def _coerce_optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _coerce_traceable_field(value: object, *, key: str, context: str) -> TraceableField:
    label = TRACEABLE_FIELD_LABELS.get(key, key.replace("_", " ").title())
    if value is None:
        return _missing_traceable_field(key, f"{context} is missing")
    if isinstance(value, bool):
        raise TypeError(f"{context} cannot be boolean")
    if isinstance(value, Mapping):
        return _coerce_traceable_field_from_mapping(
            value,
            key=key,
            context=context,
            label=label,
        )
    raise TypeError(f"{context} must be a traceable object")


def _coerce_traceable_field_from_mapping(
    payload: Mapping[str, object],
    *,
    key: str,
    context: str,
    label: str,
) -> TraceableField:
    if "value" not in payload:
        raise TypeError(f"{context} must contain 'value'")
    raw_name = payload.get("name")
    name = raw_name if isinstance(raw_name, str) and raw_name.strip() else label
    raw_value = payload.get("value")
    if isinstance(raw_value, bool):
        raise TypeError(f"{context}.value cannot be boolean")
    if raw_value is not None and not isinstance(raw_value, str | int | float):
        raise TypeError(f"{context}.value must be string | number | null")
    provenance = _coerce_provenance(
        payload.get("provenance"),
        field_key=key,
        context=context,
    )
    return TraceableField(name=name, value=raw_value, provenance=provenance)


def _normalize_provenance_type(value: object, *, context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{context}.type must be a string")
    normalized = value.strip().upper()
    if normalized not in {"XBRL", "CALCULATION", "MANUAL"}:
        raise TypeError(f"{context}.type has unsupported value: {value!r}")
    return normalized


def _coerce_provenance(
    value: object, *, field_key: str, context: str
) -> XBRLProvenance | ComputedProvenance | ManualProvenance:
    provenance_context = f"{context}.provenance"
    if value is None:
        raise TypeError(f"{provenance_context} is required")
    if not isinstance(value, Mapping):
        raise TypeError(f"{provenance_context} must be an object")

    kind = _normalize_provenance_type(value.get("type"), context=provenance_context)

    concept = value.get("concept")
    period = value.get("period")
    if isinstance(concept, str) and isinstance(period, str):
        if kind is not None and kind != "XBRL":
            raise TypeError(
                f"{provenance_context} payload is incompatible with type {kind!r}"
            )
        return XBRLProvenance(concept=concept, period=period)

    op_code = value.get("op_code")
    expression = value.get("expression")
    if isinstance(op_code, str) and isinstance(expression, str):
        if kind is not None and kind != "CALCULATION":
            raise TypeError(
                f"{provenance_context} payload is incompatible with type {kind!r}"
            )
        return ComputedProvenance(op_code=op_code, expression=expression, inputs={})

    description = value.get("description")
    if isinstance(description, str):
        if kind is not None and kind != "MANUAL":
            raise TypeError(
                f"{provenance_context} payload is incompatible with type {kind!r}"
            )
        author = value.get("author")
        if isinstance(author, str):
            return ManualProvenance(description=description, author=author)
        return ManualProvenance(description=description)

    raise TypeError(f"{provenance_context} has unsupported shape")


def _missing_traceable_field(field_key: str, reason: str) -> TraceableField:
    return TraceableField(
        name=TRACEABLE_FIELD_LABELS.get(
            field_key, field_key.replace("_", " ").strip().title()
        ),
        value=None,
        provenance=ManualProvenance(description=reason),
    )
