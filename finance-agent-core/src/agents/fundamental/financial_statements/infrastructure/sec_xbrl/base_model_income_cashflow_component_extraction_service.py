from __future__ import annotations

from src.agents.fundamental.shared.contracts.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
)

from .base_model_income_cashflow_config_service import IncomeCashflowConfigBundle
from .base_model_income_cashflow_contracts import (
    IncomeCashflowComponentFields,
    IncomeCashflowOps,
)
from .extractor import SECReportExtractor


def extract_income_cashflow_component_fields(
    *,
    extractor: SECReportExtractor,
    config_bundle: IncomeCashflowConfigBundle,
    ops: IncomeCashflowOps,
) -> IncomeCashflowComponentFields:
    preferred_stock = ops.extract_field_fn(
        extractor,
        config_bundle.preferred_stock,
        "Preferred Stock",
        target_type=float,
    )
    if preferred_stock.value is None:
        preferred_stock = TraceableField(
            name="Preferred Stock",
            value=0.0,
            provenance=ManualProvenance(
                description="Assumed 0 due to no disclosure or no implementaion now"
            ),
        )

    total_revenue = ops.extract_field_fn(
        extractor,
        config_bundle.total_revenue,
        "Total Revenue",
        target_type=float,
    )
    operating_income = ops.extract_field_fn(
        extractor,
        config_bundle.operating_income,
        "Operating Income (EBIT)",
        target_type=float,
    )
    income_before_tax = ops.extract_field_fn(
        extractor,
        config_bundle.income_before_tax,
        "Income Before Tax",
        target_type=float,
    )
    interest_expense = ops.extract_field_fn(
        extractor,
        config_bundle.interest_expense,
        "Interest Expense",
        target_type=float,
    )
    depreciation_and_amortization = ops.extract_field_fn(
        extractor,
        config_bundle.depreciation_and_amortization,
        "Depreciation & Amortization",
        target_type=float,
    )
    share_based_compensation = ops.extract_field_fn(
        extractor,
        config_bundle.share_based_compensation,
        "Share-Based Compensation",
        target_type=float,
    )
    net_income = ops.extract_field_fn(
        extractor,
        config_bundle.net_income,
        "Net Income",
        target_type=float,
    )
    income_tax_expense = ops.extract_field_fn(
        extractor,
        config_bundle.income_tax_expense,
        "Income Tax Expense",
        target_type=float,
    )

    ebitda = _build_ebitda(
        operating_income=operating_income,
        depreciation_and_amortization=depreciation_and_amortization,
    )

    operating_cash_flow = ops.extract_field_fn(
        extractor,
        config_bundle.operating_cash_flow,
        "Operating Cash Flow (OCF)",
        target_type=float,
    )
    dividends_paid = ops.extract_field_fn(
        extractor,
        config_bundle.dividends_paid,
        "Dividends Paid",
        target_type=float,
    )

    return IncomeCashflowComponentFields(
        preferred_stock=preferred_stock,
        total_revenue=total_revenue,
        operating_income=operating_income,
        income_before_tax=income_before_tax,
        interest_expense=interest_expense,
        depreciation_and_amortization=depreciation_and_amortization,
        share_based_compensation=share_based_compensation,
        net_income=net_income,
        income_tax_expense=income_tax_expense,
        ebitda=ebitda,
        operating_cash_flow=operating_cash_flow,
        dividends_paid=dividends_paid,
    )


def _build_ebitda(
    *,
    operating_income: TraceableField[float],
    depreciation_and_amortization: TraceableField[float],
) -> TraceableField[float]:
    if (
        operating_income.value is not None
        and depreciation_and_amortization.value is not None
    ):
        return TraceableField(
            name="EBITDA",
            value=operating_income.value + depreciation_and_amortization.value,
            provenance=ComputedProvenance(
                op_code="EBITDA_CALC",
                expression="OperatingIncome + DepreciationAndAmortization",
                inputs={
                    "Operating Income": operating_income,
                    "Depreciation & Amortization": depreciation_and_amortization,
                },
            ),
        )
    return TraceableField(
        name="EBITDA",
        value=None,
        provenance=ManualProvenance(description="Missing Operating Income or D&A"),
    )
