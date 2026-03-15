from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TimeframeCode = Literal["1d", "1wk", "1h"]


@dataclass(frozen=True)
class TimeframeConfig:
    code: TimeframeCode
    lookback_days: int | None = None
    timezone: str | None = None
