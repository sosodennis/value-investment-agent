from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.agents.fundamental.domain.report_semantics import (
    infer_extension_type_from_extension,
    normalize_extension_type_token,
)
from src.shared.kernel.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
    XBRLProvenance,
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
class FinancialReport:
    base: BaseFinancialModel
    extension: (
        IndustrialExtension | FinancialServicesExtension | RealEstateExtension | None
    ) = None
    industry_type: str = "General"


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


def parse_financial_reports(
    reports: list[FinancialReport | dict[str, object]],
) -> list[FinancialReport]:
    result: list[FinancialReport] = []
    for item in reports:
        if isinstance(item, FinancialReport):
            result.append(item)
            continue
        if isinstance(item, dict):
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

    extension_type = normalize_extension_type_token(
        value.get("extension_type"), context="financial report.extension_type"
    )
    if extension_type is None:
        extension_type = normalize_extension_type_token(
            value.get("industry_type"), context="financial report.industry_type"
        )
    if extension_type is None and extension_map is not None:
        extension_type = infer_extension_type_from_extension(extension_map)

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
    )


def _as_mapping(value: object, context: str) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    raise TypeError(f"{context} must be an object")


def _coerce_traceable_mapping(
    mapping: Mapping[str, object], *, context: str
) -> dict[str, TraceableField]:
    output: dict[str, TraceableField] = {}
    for key, item in mapping.items():
        output[key] = _coerce_traceable_field(item, key=key, context=f"{context}.{key}")
    return output


def _coerce_traceable_field(value: object, *, key: str, context: str) -> TraceableField:
    label = TRACEABLE_FIELD_LABELS.get(key, key.replace("_", " ").title())
    if isinstance(value, TraceableField):
        return value
    if value is None:
        return _missing_traceable_field(key, f"{context} is missing")
    if isinstance(value, Mapping):
        if "value" not in value:
            raise TypeError(f"{context} must contain 'value'")
        raw_name = value.get("name")
        name = raw_name if isinstance(raw_name, str) and raw_name.strip() else label
        raw_value = value.get("value")
        if isinstance(raw_value, bool):
            raise TypeError(f"{context}.value cannot be boolean")
        if raw_value is not None and not isinstance(raw_value, str | int | float):
            raise TypeError(f"{context}.value must be string | number | null")
        provenance = _coerce_provenance(value.get("provenance"), field_key=key)
        return TraceableField(name=name, value=raw_value, provenance=provenance)
    if isinstance(value, bool):
        raise TypeError(f"{context} cannot be boolean")
    if isinstance(value, str | int | float):
        return TraceableField(
            name=label,
            value=value,
            provenance=ManualProvenance(
                description=f"Coerced scalar value for '{key}' from canonical payload"
            ),
        )
    raise TypeError(f"{context} has unsupported type: {type(value)!r}")


def _coerce_provenance(
    value: object, *, field_key: str
) -> XBRLProvenance | ComputedProvenance | ManualProvenance:
    if isinstance(value, XBRLProvenance | ComputedProvenance | ManualProvenance):
        return value
    if isinstance(value, Mapping):
        concept = value.get("concept")
        period = value.get("period")
        if isinstance(concept, str) and isinstance(period, str):
            return XBRLProvenance(concept=concept, period=period)

        op_code = value.get("op_code")
        expression = value.get("expression")
        if isinstance(op_code, str) and isinstance(expression, str):
            return ComputedProvenance(op_code=op_code, expression=expression, inputs={})

        description = value.get("description")
        if isinstance(description, str):
            author = value.get("author")
            if isinstance(author, str):
                return ManualProvenance(description=description, author=author)
            return ManualProvenance(description=description)
    return ManualProvenance(description=f"Imported provenance for '{field_key}'")


def _missing_traceable_field(field_key: str, reason: str) -> TraceableField:
    return TraceableField(
        name=TRACEABLE_FIELD_LABELS.get(
            field_key, field_key.replace("_", " ").strip().title()
        ),
        value=None,
        provenance=ManualProvenance(description=reason),
    )
