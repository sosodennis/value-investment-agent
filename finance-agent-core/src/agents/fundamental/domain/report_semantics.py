from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

FUNDAMENTAL_BASE_KEYS: tuple[str, ...] = (
    "fiscal_year",
    "fiscal_period",
    "period_end_date",
    "currency",
    "company_name",
    "cik",
    "sic_code",
    "shares_outstanding",
    "total_revenue",
    "net_income",
    "income_tax_expense",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "cash_and_equivalents",
    "operating_cash_flow",
)

INDUSTRIAL_EXTENSION_KEYS: tuple[str, ...] = (
    "inventory",
    "accounts_receivable",
    "cogs",
    "rd_expense",
    "sga_expense",
    "selling_expense",
    "ga_expense",
    "capex",
)

FINANCIAL_SERVICES_EXTENSION_KEYS: tuple[str, ...] = (
    "loans_and_leases",
    "deposits",
    "allowance_for_credit_losses",
    "interest_income",
    "interest_expense",
    "provision_for_loan_losses",
    "risk_weighted_assets",
    "tier1_capital_ratio",
)

REAL_ESTATE_EXTENSION_KEYS: tuple[str, ...] = (
    "real_estate_assets",
    "accumulated_depreciation",
    "depreciation_and_amortization",
    "gain_on_sale",
    "ffo",
)


def normalize_extension_type_token(value: object, *, context: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        value = value.value
    if not isinstance(value, str):
        raise TypeError(f"{context} must be a string")
    normalized = value.strip().lower()
    if normalized == "industrial":
        return "Industrial"
    if normalized in {
        "financialservices",
        "financial_services",
        "financial services",
        "financial",
    }:
        return "FinancialServices"
    if normalized in {"realestate", "real_estate", "real estate"}:
        return "RealEstate"
    if normalized == "general":
        return None
    raise TypeError(f"{context} has unsupported value: {value!r}")


def infer_extension_type_from_extension(extension: Mapping[str, object]) -> str | None:
    if any(key in extension for key in INDUSTRIAL_EXTENSION_KEYS):
        return "Industrial"
    if any(key in extension for key in FINANCIAL_SERVICES_EXTENSION_KEYS):
        return "FinancialServices"
    if any(key in extension for key in REAL_ESTATE_EXTENSION_KEYS):
        return "RealEstate"
    return None
