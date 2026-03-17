"""Shared domain contracts for the technical analysis agent."""

from .feature_pack import FeatureFrame, FeaturePack
from .fusion_signal import FusionDiagnostics, FusionSignal
from .indicator_snapshot import IndicatorSnapshot
from .pattern_pack import (
    KeyLevel,
    PatternFlag,
    PatternFrame,
    PatternPack,
    VolumeProfileSummary,
)
from .price_bar import PriceBar, PriceSeries
from .time_alignment_guard import AlignmentReport, TimeAlignmentGuard
from .time_alignment_guard_service import TimeAlignmentGuardService
from .timeframe import TimeframeCode, TimeframeConfig

__all__ = [
    "AlignmentReport",
    "TimeAlignmentGuardService",
    "FeatureFrame",
    "FeaturePack",
    "FusionDiagnostics",
    "FusionSignal",
    "IndicatorSnapshot",
    "KeyLevel",
    "PatternFlag",
    "PatternFrame",
    "PatternPack",
    "VolumeProfileSummary",
    "PriceBar",
    "PriceSeries",
    "TimeAlignmentGuard",
    "TimeframeCode",
    "TimeframeConfig",
]
