"""Stable financial statement payload contracts and parsers."""

from .interface.contracts import (
    FinancialReportBaseLike,
    FinancialReportLike,
    FinancialReportModel,
    FundamentalBaseModel,
    TraceableFieldModel,
    parse_financial_reports_model,
)
from .interface.parsers import (
    FinancialStatementsPayload,
    parse_calculation_metrics,
    parse_financial_statements_payload,
    parse_valuation_model_runtime,
)
from .interface.types import (
    FundamentalText,
    OptionalFundamentalNumber,
    OptionalFundamentalText,
    TraceableOptionalText,
    TraceableProvenance,
    TraceableValue,
)

__all__ = [
    "FinancialReportBaseLike",
    "FinancialReportLike",
    "FinancialReportModel",
    "FinancialStatementsPayload",
    "FundamentalBaseModel",
    "FundamentalText",
    "OptionalFundamentalNumber",
    "OptionalFundamentalText",
    "TraceableFieldModel",
    "TraceableOptionalText",
    "TraceableProvenance",
    "TraceableValue",
    "parse_calculation_metrics",
    "parse_financial_reports_model",
    "parse_financial_statements_payload",
    "parse_valuation_model_runtime",
]
