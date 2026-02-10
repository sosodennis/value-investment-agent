"""
SEC XBRL extraction and mapping utilities.
"""

from .extractor import SearchConfig, SearchType, SECReportExtractor
from .factory import FinancialReportFactory
from .mapping import REGISTRY
from .models import (
    BaseFinancialModel,
    ComputedProvenance,
    FinancialReport,
    FinancialServicesExtension,
    IndustrialExtension,
    ManualProvenance,
    RealEstateExtension,
    TraceableField,
    XBRLProvenance,
)
from .utils import fetch_financial_data

__all__ = [
    "SearchConfig",
    "SearchType",
    "SECReportExtractor",
    "FinancialReportFactory",
    "REGISTRY",
    "BaseFinancialModel",
    "ComputedProvenance",
    "FinancialReport",
    "FinancialServicesExtension",
    "IndustrialExtension",
    "ManualProvenance",
    "RealEstateExtension",
    "TraceableField",
    "XBRLProvenance",
    "fetch_financial_data",
]
