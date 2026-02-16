"""
SEC XBRL extraction and mapping utilities.
"""

from src.shared.kernel.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
    XBRLProvenance,
)

from .extractor import SearchConfig, SearchType, SECReportExtractor
from .factory import FinancialReportFactory
from .mapping import REGISTRY
from .models import (
    BaseFinancialModel,
    FinancialReport,
    FinancialServicesExtension,
    IndustrialExtension,
    RealEstateExtension,
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
