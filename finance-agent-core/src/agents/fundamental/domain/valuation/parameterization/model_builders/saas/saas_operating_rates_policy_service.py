from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.shared.kernel.traceable import TraceableField

from ....policies.manual_assumption_policy import DEFAULT_DA_RATE, assume_rate
from ....report_contract import FinancialReport, IndustrialExtension
from ...core_ops_service import ratio_with_optional_inputs


@dataclass(frozen=True)
class SaasOperatingRates:
    margin_tf: TraceableField[float]
    tax_rate_tf: TraceableField[float]
    da_rate_tf: TraceableField[float]
    capex_rate_tf: TraceableField[float]
    sbc_rate_tf: TraceableField[float]
    wc_rate_tf: TraceableField[float]


def build_saas_operating_rates(
    *,
    latest: FinancialReport,
    reports: list[FinancialReport],
    revenue_tf: TraceableField[float],
    ratio: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ],
    subtract: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ],
    missing_field: Callable[[str, str], TraceableField[float]],
    assumptions: list[str],
) -> SaasOperatingRates:
    base = latest.base
    extension = (
        latest.extension if isinstance(latest.extension, IndustrialExtension) else None
    )

    operating_income_tf = base.operating_income
    tax_expense_tf = base.income_tax_expense
    income_before_tax_tf = base.income_before_tax
    da_tf = base.depreciation_and_amortization
    sbc_tf = base.share_based_compensation
    capex_tf = extension.capex if extension else None

    margin_tf = ratio(
        "Operating Margin",
        operating_income_tf,
        revenue_tf,
        "OperatingIncome / Revenue",
    )
    tax_rate_tf = ratio(
        "Tax Rate",
        tax_expense_tf,
        income_before_tax_tf,
        "IncomeTaxExpense / IncomeBeforeTax",
    )
    da_rate_tf = ratio(
        "D&A Rate",
        da_tf,
        revenue_tf,
        "DepreciationAndAmortization / Revenue",
    )
    if da_rate_tf.value is None:
        da_rate_tf = assume_rate(
            "D&A Rate",
            DEFAULT_DA_RATE,
            "Policy default D&A rate (preview only; requires analyst review)",
        )
        assumptions.append(f"da_rates defaulted to {DEFAULT_DA_RATE:.2%}")

    capex_rate_tf = ratio_with_optional_inputs(
        name="CapEx Rate",
        numerator=capex_tf,
        denominator=revenue_tf,
        expression="CapEx / Revenue",
        missing_reason="Missing CapEx for CapEx Rate",
        ratio_op=ratio,
        missing_field_op=missing_field,
    )
    sbc_rate_tf = ratio(
        "SBC Rate",
        sbc_tf,
        revenue_tf,
        "ShareBasedCompensation / Revenue",
    )

    current_assets_tf = base.current_assets
    current_liabilities_tf = base.current_liabilities
    wc_latest = subtract(
        "Working Capital (Latest)",
        current_assets_tf,
        current_liabilities_tf,
        "CurrentAssets - CurrentLiabilities",
    )
    wc_prev = None
    if len(reports) > 1:
        prev = reports[1]
        wc_prev = subtract(
            "Working Capital (Previous)",
            prev.base.current_assets,
            prev.base.current_liabilities,
            "Prev CurrentAssets - Prev CurrentLiabilities",
        )

    if (
        wc_prev is not None
        and wc_prev.value is not None
        and wc_latest.value is not None
    ):
        wc_delta = subtract(
            "Working Capital Delta",
            wc_latest,
            wc_prev,
            "WorkingCapitalLatest - WorkingCapitalPrevious",
        )
        wc_rate_tf = ratio("WC Rate", wc_delta, revenue_tf, "ChangeInWC / Revenue")
    else:
        wc_rate_tf = missing_field("WC Rate", "Missing working capital history")

    return SaasOperatingRates(
        margin_tf=margin_tf,
        tax_rate_tf=tax_rate_tf,
        da_rate_tf=da_rate_tf,
        capex_rate_tf=capex_rate_tf,
        sbc_rate_tf=sbc_rate_tf,
        wc_rate_tf=wc_rate_tf,
    )
