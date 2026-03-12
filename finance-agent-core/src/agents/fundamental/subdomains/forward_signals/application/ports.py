from __future__ import annotations

from typing import Protocol

from src.agents.fundamental.subdomains.financial_statements.interface.contracts import (
    FinancialReportLike,
)
from src.agents.fundamental.subdomains.forward_signals.interface.contracts import (
    ForwardSignalPayload,
)
from src.shared.kernel.types import JSONObject


class ForwardSignalXbrlExtractor(Protocol):
    def __call__(
        self, *, ticker: str, reports: list[FinancialReportLike]
    ) -> list[dict[str, object]]: ...


class ForwardSignalTextExtractor(Protocol):
    def __call__(
        self, *, ticker: str, rules_sector: str | None = None
    ) -> list[dict[str, object]]: ...


class FinbertAnalysisResult(Protocol):
    label: str
    score: float


class FinbertAnalyzer(Protocol):
    def is_available(self) -> bool: ...

    def analyze(self, text: str) -> FinbertAnalysisResult | None: ...


class FinbertAnalyzerProvider(Protocol):
    def __call__(self) -> FinbertAnalyzer: ...


class ForwardSignalsProvider(Protocol):
    def __call__(
        self, *, ticker: str, reports_raw: list[JSONObject]
    ) -> list[ForwardSignalPayload] | None: ...


__all__ = [
    "FinbertAnalysisResult",
    "FinbertAnalyzer",
    "FinbertAnalyzerProvider",
    "ForwardSignalTextExtractor",
    "ForwardSignalXbrlExtractor",
    "ForwardSignalsProvider",
]
