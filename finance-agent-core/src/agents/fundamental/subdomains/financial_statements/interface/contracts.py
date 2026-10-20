"""Compatibility exports for shared financial statement artifact contracts."""

from src.shared.artifacts.financial_statement_contracts import (
    CANONICAL_EXTENSION_TYPES,
    CANONICAL_INDUSTRY_TYPES,
    FilingMetadataModel,
    FinancialReportBaseLike,
    FinancialReportLike,
    FinancialReportModel,
    FinancialServicesExtensionModel,
    FundamentalBaseModel,
    IndustrialExtensionModel,
    RealEstateExtensionModel,
    TraceableFieldModel,
    parse_financial_reports_model,
)

__all__ = [
    "CANONICAL_EXTENSION_TYPES",
    "CANONICAL_INDUSTRY_TYPES",
    "FinancialReportBaseLike",
    "FinancialReportLike",
    "FinancialReportModel",
    "FilingMetadataModel",
    "FinancialServicesExtensionModel",
    "FundamentalBaseModel",
    "IndustrialExtensionModel",
    "RealEstateExtensionModel",
    "TraceableFieldModel",
    "parse_financial_reports_model",
]
