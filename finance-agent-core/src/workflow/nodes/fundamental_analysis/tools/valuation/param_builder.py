from __future__ import annotations

from dataclasses import dataclass

from src.common.traceable import ComputedProvenance, ManualProvenance, TraceableField

from ..sec_xbrl.models import (
    FinancialReport,
    FinancialServicesExtension,
    IndustrialExtension,
    RealEstateExtension,
)
from .assumptions import (
    DEFAULT_DA_RATE,
    DEFAULT_TERMINAL_GROWTH,
    DEFAULT_WACC,
    assume_rate,
)

TraceInput = TraceableField[float] | TraceableField[list[float]]


@dataclass(frozen=True)
class ParamBuildResult:
    params: dict[str, object]
    trace_inputs: dict[str, TraceInput]
    missing: list[str]
    assumptions: list[str]


PROJECTION_YEARS = 5


def build_params(
    model_type: str,
    ticker: str | None,
    reports_raw: list[FinancialReport | dict] | None,
) -> ParamBuildResult:
    reports = _coerce_reports(reports_raw or [])
    if not reports:
        raise ValueError("No SEC XBRL financial reports available")

    reports_sorted = sorted(reports, key=_report_year, reverse=True)
    latest = reports_sorted[0]

    if model_type == "saas":
        return _build_saas_params(ticker, latest, reports_sorted)
    if model_type == "bank":
        return _build_bank_params(ticker, latest, reports_sorted)
    if model_type == "ev_revenue":
        return _build_ev_revenue_params(ticker, latest)
    if model_type == "ev_ebitda":
        return _build_ev_ebitda_params(ticker, latest)
    if model_type == "reit_ffo":
        return _build_reit_ffo_params(ticker, latest)
    if model_type == "residual_income":
        return _build_residual_income_params(ticker, latest)
    if model_type == "eva":
        return _build_eva_params(ticker, latest)

    raise ValueError(f"Unsupported model type for SEC XBRL builder: {model_type}")


def _coerce_reports(reports: list[FinancialReport | dict]) -> list[FinancialReport]:
    result: list[FinancialReport] = []
    for item in reports:
        if isinstance(item, FinancialReport):
            result.append(item)
        elif isinstance(item, dict):
            result.append(FinancialReport.model_validate(item))
    return result


def _report_year(report: FinancialReport) -> int:
    value = report.base.fiscal_year.value
    if value is None:
        return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _missing_field(name: str, reason: str) -> TraceableField[float]:
    return TraceableField(
        name=name,
        value=None,
        provenance=ManualProvenance(description=reason),
    )


def _computed_field(
    name: str,
    value: float | list[float],
    op_code: str,
    expression: str,
    inputs: dict[str, TraceableField],
) -> TraceableField:
    return TraceableField(
        name=name,
        value=value,
        provenance=ComputedProvenance(
            op_code=op_code,
            expression=expression,
            inputs=inputs,
        ),
    )


def _ratio(
    name: str,
    numerator: TraceableField[float],
    denominator: TraceableField[float],
    expression: str,
) -> TraceableField[float]:
    if numerator.value is None or denominator.value in (None, 0):
        return _missing_field(name, f"Missing or zero denominator for {expression}")
    value = float(numerator.value) / float(denominator.value)
    return _computed_field(
        name=name,
        value=value,
        op_code="DIV",
        expression=expression,
        inputs={numerator.name: numerator, denominator.name: denominator},
    )


def _subtract(
    name: str,
    left: TraceableField[float],
    right: TraceableField[float],
    expression: str,
) -> TraceableField[float]:
    if left.value is None or right.value is None:
        return _missing_field(name, f"Missing inputs for {expression}")
    value = float(left.value) - float(right.value)
    return _computed_field(
        name=name,
        value=value,
        op_code="SUB",
        expression=expression,
        inputs={left.name: left, right.name: right},
    )


def _repeat_rate(
    name: str, rate: TraceableField[float], count: int
) -> TraceableField[list[float]]:
    if rate.value is None:
        return TraceableField(
            name=name,
            value=None,
            provenance=ManualProvenance(description=f"Missing base rate for {name}"),
        )
    values = [float(rate.value)] * count
    return _computed_field(
        name=name,
        value=values,
        op_code="REPEAT",
        expression=f"Repeat {rate.name} for {count} years",
        inputs={rate.name: rate},
    )


def _growth_rates_from_series(
    name: str,
    series: list[TraceableField[float]],
    count: int,
) -> TraceableField[list[float]]:
    values: list[float] = []
    inputs: dict[str, TraceableField] = {}

    for idx in range(len(series) - 1):
        current = series[idx]
        previous = series[idx + 1]
        inputs[f"{current.name} (t-{idx})"] = current
        inputs[f"{previous.name} (t-{idx + 1})"] = previous
        if current.value is None or previous.value in (None, 0):
            continue
        values.append(float(current.value) / float(previous.value) - 1.0)

    if not values:
        return TraceableField(
            name=name,
            value=None,
            provenance=ManualProvenance(description="Insufficient history for growth"),
        )

    avg_growth = sum(values) / len(values)
    projected = [avg_growth] * count
    return _computed_field(
        name=name,
        value=projected,
        op_code="YOY_GROWTH_AVG",
        expression="Average historical YoY growth (SEC XBRL)",
        inputs=inputs,
    )


def _value_or_missing(
    tf: TraceableField[float] | None,
    field_name: str,
    missing: list[str],
) -> float | None:
    if tf is None or tf.value is None:
        missing.append(field_name)
        return None
    return float(tf.value)


def _dedupe_missing(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _build_saas_params(
    ticker: str | None,
    latest: FinancialReport,
    reports: list[FinancialReport],
) -> ParamBuildResult:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base
    extension = (
        latest.extension if isinstance(latest.extension, IndustrialExtension) else None
    )

    revenue_tf = base.total_revenue
    shares_tf = base.shares_outstanding
    cash_tf = base.cash_and_equivalents
    debt_tf = base.total_debt
    preferred_tf = base.preferred_stock

    operating_income_tf = base.operating_income
    tax_expense_tf = base.income_tax_expense
    income_before_tax_tf = base.income_before_tax
    da_tf = base.depreciation_and_amortization
    sbc_tf = base.share_based_compensation
    capex_tf = extension.capex if extension else None

    current_assets_tf = base.current_assets
    current_liabilities_tf = base.current_liabilities

    margin_tf = _ratio(
        "Operating Margin",
        operating_income_tf,
        revenue_tf,
        "OperatingIncome / Revenue",
    )
    tax_rate_tf = _ratio(
        "Tax Rate",
        tax_expense_tf,
        income_before_tax_tf,
        "IncomeTaxExpense / IncomeBeforeTax",
    )
    da_rate_tf = _ratio(
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
    capex_rate_tf = (
        _ratio("CapEx Rate", capex_tf, revenue_tf, "CapEx / Revenue")
        if capex_tf is not None
        else _missing_field("CapEx Rate", "Missing CapEx for CapEx Rate")
    )
    sbc_rate_tf = _ratio(
        "SBC Rate",
        sbc_tf,
        revenue_tf,
        "ShareBasedCompensation / Revenue",
    )

    wc_latest = _subtract(
        "Working Capital (Latest)",
        current_assets_tf,
        current_liabilities_tf,
        "CurrentAssets - CurrentLiabilities",
    )
    wc_prev = None
    if len(reports) > 1:
        prev = reports[1]
        wc_prev = _subtract(
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
        wc_delta = _subtract(
            "Working Capital Delta",
            wc_latest,
            wc_prev,
            "WorkingCapitalLatest - WorkingCapitalPrevious",
        )
        wc_rate_tf = _ratio(
            "WC Rate",
            wc_delta,
            revenue_tf,
            "ChangeInWC / Revenue",
        )
    else:
        wc_rate_tf = _missing_field("WC Rate", "Missing working capital history")

    revenue_series = [r.base.total_revenue for r in reports]
    growth_rates_tf = _growth_rates_from_series(
        "Revenue Growth Rates", revenue_series, PROJECTION_YEARS
    )

    operating_margins_tf = _repeat_rate(
        "Operating Margins", margin_tf, PROJECTION_YEARS
    )
    da_rates_tf = _repeat_rate("D&A Rates", da_rate_tf, PROJECTION_YEARS)
    capex_rates_tf = _repeat_rate("CapEx Rates", capex_rate_tf, PROJECTION_YEARS)
    wc_rates_tf = _repeat_rate("WC Rates", wc_rate_tf, PROJECTION_YEARS)
    sbc_rates_tf = _repeat_rate("SBC Rates", sbc_rate_tf, PROJECTION_YEARS)

    initial_revenue = _value_or_missing(revenue_tf, "initial_revenue", missing)
    shares_outstanding = _value_or_missing(shares_tf, "shares_outstanding", missing)
    cash = _value_or_missing(cash_tf, "cash", missing)
    total_debt = _value_or_missing(debt_tf, "total_debt", missing)
    preferred_stock = _value_or_missing(preferred_tf, "preferred_stock", missing)

    if growth_rates_tf.value is None:
        missing.append("growth_rates")
    if operating_margins_tf.value is None:
        missing.append("operating_margins")
    if tax_rate_tf.value is None:
        missing.append("tax_rate")
    if da_rates_tf.value is None:
        missing.append("da_rates")
    if capex_rates_tf.value is None:
        missing.append("capex_rates")
    if wc_rates_tf.value is None:
        missing.append("wc_rates")
    if sbc_rates_tf.value is None:
        missing.append("sbc_rates")

    # Enterprise-grade note: defaults are only for preview; require analyst review in production.
    wacc_tf = assume_rate(
        "WACC",
        DEFAULT_WACC,
        "Policy default WACC (preview only; requires analyst review)",
    )
    terminal_growth_tf = assume_rate(
        "Terminal Growth",
        DEFAULT_TERMINAL_GROWTH,
        "Policy default terminal growth (preview only; requires analyst review)",
    )
    assumptions.append(f"wacc defaulted to {DEFAULT_WACC:.2%}")
    assumptions.append(f"terminal_growth defaulted to {DEFAULT_TERMINAL_GROWTH:.2%}")

    trace_inputs: dict[str, TraceInput] = {
        "initial_revenue": revenue_tf,
        "growth_rates": growth_rates_tf,
        "operating_margins": operating_margins_tf,
        "tax_rate": tax_rate_tf,
        "da_rates": da_rates_tf,
        "capex_rates": capex_rates_tf,
        "wc_rates": wc_rates_tf,
        "sbc_rates": sbc_rates_tf,
        "wacc": wacc_tf,
        "terminal_growth": terminal_growth_tf,
        "cash": cash_tf,
        "total_debt": debt_tf,
        "preferred_stock": preferred_tf,
        "shares_outstanding": shares_tf,
    }

    rationale = "Derived from SEC XBRL (financial reports) with computed rates."
    if assumptions:
        rationale += " Controlled assumptions applied: " + "; ".join(assumptions)

    params = {
        "ticker": ticker or "UNKNOWN",
        "rationale": rationale,
        "initial_revenue": initial_revenue,
        "growth_rates": growth_rates_tf.value,
        "operating_margins": operating_margins_tf.value,
        "tax_rate": tax_rate_tf.value,
        "da_rates": da_rates_tf.value,
        "capex_rates": capex_rates_tf.value,
        "wc_rates": wc_rates_tf.value,
        "sbc_rates": sbc_rates_tf.value,
        "wacc": wacc_tf.value,
        "terminal_growth": terminal_growth_tf.value,
        "shares_outstanding": shares_outstanding,
        "cash": cash,
        "total_debt": total_debt,
        "preferred_stock": preferred_stock,
        "current_price": None,
    }

    return ParamBuildResult(
        params=params,
        trace_inputs=trace_inputs,
        missing=_dedupe_missing(missing),
        assumptions=assumptions,
    )


def _build_ev_revenue_params(
    ticker: str | None, latest: FinancialReport
) -> ParamBuildResult:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base

    revenue_tf = base.total_revenue
    shares_tf = base.shares_outstanding
    cash_tf = base.cash_and_equivalents
    debt_tf = base.total_debt
    preferred_tf = base.preferred_stock

    revenue = _value_or_missing(revenue_tf, "revenue", missing)
    shares_outstanding = _value_or_missing(shares_tf, "shares_outstanding", missing)
    cash = _value_or_missing(cash_tf, "cash", missing)
    total_debt = _value_or_missing(debt_tf, "total_debt", missing)
    preferred_stock = _value_or_missing(preferred_tf, "preferred_stock", missing)

    missing.append("ev_revenue_multiple")

    trace_inputs: dict[str, TraceInput] = {
        "target_metric": revenue_tf,
        "cash": cash_tf,
        "total_debt": debt_tf,
        "preferred_stock": preferred_tf,
        "shares_outstanding": shares_tf,
    }

    params = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "revenue": revenue,
        "ev_revenue_multiple": None,
        "cash": cash,
        "total_debt": total_debt,
        "preferred_stock": preferred_stock,
        "shares_outstanding": shares_outstanding,
        "current_price": None,
    }

    return ParamBuildResult(
        params=params,
        trace_inputs=trace_inputs,
        missing=_dedupe_missing(missing),
        assumptions=assumptions,
    )


def _build_ev_ebitda_params(
    ticker: str | None, latest: FinancialReport
) -> ParamBuildResult:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base

    ebitda_tf = base.ebitda
    shares_tf = base.shares_outstanding
    cash_tf = base.cash_and_equivalents
    debt_tf = base.total_debt
    preferred_tf = base.preferred_stock

    ebitda = _value_or_missing(ebitda_tf, "ebitda", missing)
    shares_outstanding = _value_or_missing(shares_tf, "shares_outstanding", missing)
    cash = _value_or_missing(cash_tf, "cash", missing)
    total_debt = _value_or_missing(debt_tf, "total_debt", missing)
    preferred_stock = _value_or_missing(preferred_tf, "preferred_stock", missing)

    missing.append("ev_ebitda_multiple")

    trace_inputs: dict[str, TraceInput] = {
        "target_metric": ebitda_tf,
        "cash": cash_tf,
        "total_debt": debt_tf,
        "preferred_stock": preferred_tf,
        "shares_outstanding": shares_tf,
    }

    params = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "ebitda": ebitda,
        "ev_ebitda_multiple": None,
        "cash": cash,
        "total_debt": total_debt,
        "preferred_stock": preferred_stock,
        "shares_outstanding": shares_outstanding,
        "current_price": None,
    }

    return ParamBuildResult(
        params=params,
        trace_inputs=trace_inputs,
        missing=_dedupe_missing(missing),
        assumptions=assumptions,
    )


def _build_reit_ffo_params(
    ticker: str | None, latest: FinancialReport
) -> ParamBuildResult:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base
    extension = (
        latest.extension if isinstance(latest.extension, RealEstateExtension) else None
    )

    ffo_tf = extension.ffo if extension else None
    shares_tf = base.shares_outstanding
    cash_tf = base.cash_and_equivalents
    debt_tf = base.total_debt
    preferred_tf = base.preferred_stock

    ffo = _value_or_missing(ffo_tf, "ffo", missing)
    shares_outstanding = _value_or_missing(shares_tf, "shares_outstanding", missing)
    cash = _value_or_missing(cash_tf, "cash", missing)
    total_debt = _value_or_missing(debt_tf, "total_debt", missing)
    preferred_stock = _value_or_missing(preferred_tf, "preferred_stock", missing)

    missing.append("ffo_multiple")

    trace_inputs: dict[str, TraceInput] = {
        "ffo": ffo_tf if ffo_tf is not None else _missing_field("FFO", "Missing FFO"),
        "cash": cash_tf,
        "total_debt": debt_tf,
        "preferred_stock": preferred_tf,
        "shares_outstanding": shares_tf,
    }

    params = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "ffo": ffo,
        "ffo_multiple": None,
        "cash": cash,
        "total_debt": total_debt,
        "preferred_stock": preferred_stock,
        "shares_outstanding": shares_outstanding,
        "current_price": None,
    }

    return ParamBuildResult(
        params=params,
        trace_inputs=trace_inputs,
        missing=_dedupe_missing(missing),
        assumptions=assumptions,
    )


def _build_bank_params(
    ticker: str | None,
    latest: FinancialReport,
    reports: list[FinancialReport],
) -> ParamBuildResult:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base
    extension = (
        latest.extension
        if isinstance(latest.extension, FinancialServicesExtension)
        else None
    )

    net_income_tf = base.net_income
    total_equity_tf = base.total_equity
    rwa_tf = extension.risk_weighted_assets if extension else None
    tier1_tf = extension.tier1_capital_ratio if extension else None

    income_series = [r.base.net_income for r in reports]
    income_growth_tf = _growth_rates_from_series(
        "Net Income Growth Rates", income_series, PROJECTION_YEARS
    )

    rwa_intensity_tf = (
        _ratio(
            "RWA Intensity",
            rwa_tf,
            base.total_assets,
            "RiskWeightedAssets / TotalAssets",
        )
        if rwa_tf is not None
        else _missing_field("RWA Intensity", "Missing Risk-Weighted Assets")
    )

    initial_net_income = _value_or_missing(net_income_tf, "initial_net_income", missing)
    initial_capital = _value_or_missing(total_equity_tf, "initial_capital", missing)

    if income_growth_tf.value is None:
        missing.append("income_growth_rates")
    if rwa_intensity_tf.value is None:
        missing.append("rwa_intensity")
    if tier1_tf is None or tier1_tf.value is None:
        missing.append("tier1_target_ratio")

    missing.extend(["cost_of_equity", "terminal_growth"])

    trace_inputs: dict[str, TraceInput] = {
        "initial_net_income": net_income_tf,
        "income_growth_rates": income_growth_tf,
        "rwa_intensity": rwa_intensity_tf,
        "tier1_target_ratio": tier1_tf
        if tier1_tf is not None
        else _missing_field("Tier1 Target Ratio", "Missing Tier 1 ratio"),
        "initial_capital": total_equity_tf,
    }

    params = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "initial_net_income": initial_net_income,
        "income_growth_rates": income_growth_tf.value,
        "rwa_intensity": rwa_intensity_tf.value,
        "tier1_target_ratio": tier1_tf.value if tier1_tf is not None else None,
        "initial_capital": initial_capital,
        "cost_of_equity": None,
        "terminal_growth": None,
    }

    return ParamBuildResult(
        params=params,
        trace_inputs=trace_inputs,
        missing=_dedupe_missing(missing),
        assumptions=assumptions,
    )


def _build_residual_income_params(
    ticker: str | None, latest: FinancialReport
) -> ParamBuildResult:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base

    book_value_tf = base.total_equity
    shares_tf = base.shares_outstanding

    current_book_value = _value_or_missing(book_value_tf, "current_book_value", missing)
    shares_outstanding = _value_or_missing(shares_tf, "shares_outstanding", missing)

    missing.extend(["projected_residual_incomes", "required_return", "terminal_growth"])

    trace_inputs: dict[str, TraceInput] = {
        "current_book_value": book_value_tf,
        "shares_outstanding": shares_tf,
    }

    params = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "current_book_value": current_book_value,
        "projected_residual_incomes": None,
        "required_return": None,
        "terminal_growth": None,
        "terminal_residual_income": None,
        "shares_outstanding": shares_outstanding,
        "current_price": None,
    }

    return ParamBuildResult(
        params=params,
        trace_inputs=trace_inputs,
        missing=_dedupe_missing(missing),
        assumptions=assumptions,
    )


def _build_eva_params(ticker: str | None, latest: FinancialReport) -> ParamBuildResult:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base

    equity_tf = base.total_equity
    debt_tf = base.total_debt
    cash_tf = base.cash_and_equivalents
    shares_tf = base.shares_outstanding
    preferred_tf = base.preferred_stock

    if equity_tf.value is None or debt_tf.value is None or cash_tf.value is None:
        invested_capital_tf = _missing_field(
            "Invested Capital", "Missing equity, debt, or cash"
        )
    else:
        invested_capital_tf = _computed_field(
            name="Invested Capital",
            value=(
                float(equity_tf.value) + float(debt_tf.value) - float(cash_tf.value)
            ),
            op_code="INVESTED_CAPITAL",
            expression="TotalEquity + TotalDebt - Cash",
            inputs={
                "Total Equity": equity_tf,
                "Total Debt": debt_tf,
                "Cash": cash_tf,
            },
        )

    current_invested_capital = _value_or_missing(
        invested_capital_tf, "current_invested_capital", missing
    )
    shares_outstanding = _value_or_missing(shares_tf, "shares_outstanding", missing)
    cash = _value_or_missing(cash_tf, "cash", missing)
    total_debt = _value_or_missing(debt_tf, "total_debt", missing)
    preferred_stock = _value_or_missing(preferred_tf, "preferred_stock", missing)

    missing.extend(["projected_evas", "wacc", "terminal_growth"])

    trace_inputs: dict[str, TraceInput] = {
        "current_invested_capital": invested_capital_tf,
        "cash": cash_tf,
        "total_debt": debt_tf,
        "preferred_stock": preferred_tf,
        "shares_outstanding": shares_tf,
    }

    params = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "current_invested_capital": current_invested_capital,
        "projected_evas": None,
        "wacc": None,
        "terminal_growth": None,
        "terminal_eva": None,
        "cash": cash,
        "total_debt": total_debt,
        "preferred_stock": preferred_stock,
        "shares_outstanding": shares_outstanding,
        "current_price": None,
    }

    return ParamBuildResult(
        params=params,
        trace_inputs=trace_inputs,
        missing=_dedupe_missing(missing),
        assumptions=assumptions,
    )
