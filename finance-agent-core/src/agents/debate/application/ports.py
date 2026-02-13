from __future__ import annotations

from typing import Protocol


class SycophancyDetectorPort(Protocol):
    def check_consensus(
        self, bull_thesis: str, bear_thesis: str, threshold: float = 0.8
    ) -> tuple[float, bool]: ...
