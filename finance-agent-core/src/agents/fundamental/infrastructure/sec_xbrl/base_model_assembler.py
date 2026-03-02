from __future__ import annotations

from src.shared.kernel.traceable import ManualProvenance, TraceableField

from .base_model_context_balance_builder import ContextBalanceFields
from .base_model_income_cashflow_builder import IncomeCashflowDerivedFields
from .report_contracts import BaseFinancialModel


def assemble_base_financial_model(
    *,
    context_balance: ContextBalanceFields,
    total_debt: TraceableField[float],
    income_cashflow: IncomeCashflowDerivedFields,
) -> BaseFinancialModel:
    return BaseFinancialModel(
        ticker=context_balance.ticker,
        cik=context_balance.cik,
        company_name=context_balance.company_name,
        sic_code=context_balance.sic_code,
        fiscal_year=context_balance.fiscal_year,
        fiscal_period=context_balance.fiscal_period,
        shares_outstanding=context_balance.shares_outstanding,
        total_assets=context_balance.total_assets,
        total_liabilities=context_balance.total_liabilities,
        total_equity=context_balance.total_equity,
        cash_and_equivalents=context_balance.cash_and_equivalents,
        current_assets=context_balance.current_assets,
        current_liabilities=context_balance.current_liabilities,
        total_debt=total_debt,
        preferred_stock=income_cashflow.preferred_stock,
        total_revenue=income_cashflow.total_revenue,
        operating_income=income_cashflow.operating_income,
        income_before_tax=income_cashflow.income_before_tax,
        interest_expense=income_cashflow.interest_expense,
        depreciation_and_amortization=income_cashflow.depreciation_and_amortization,
        share_based_compensation=income_cashflow.share_based_compensation,
        net_income=income_cashflow.net_income,
        income_tax_expense=income_cashflow.income_tax_expense,
        ebitda=income_cashflow.ebitda,
        operating_cash_flow=income_cashflow.operating_cash_flow,
        dividends_paid=income_cashflow.dividends_paid,
        working_capital=income_cashflow.working_capital,
        working_capital_delta=TraceableField(
            name="Working Capital Delta",
            value=None,
            provenance=ManualProvenance(
                description="Requires prior period working capital"
            ),
        ),
        effective_tax_rate=income_cashflow.effective_tax_rate,
        interest_cost_rate=income_cashflow.interest_cost_rate,
        ebit_margin=income_cashflow.ebit_margin,
        net_margin=income_cashflow.net_margin,
        invested_capital=income_cashflow.invested_capital,
        nopat=income_cashflow.nopat,
        roic=income_cashflow.roic,
        reinvestment_rate=TraceableField(
            name="Reinvestment Rate",
            value=None,
            provenance=ManualProvenance(
                description="Requires CapEx, D&A, delta WC, NOPAT"
            ),
        ),
    )
