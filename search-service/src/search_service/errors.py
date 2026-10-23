from __future__ import annotations

from dataclasses import dataclass

from .contracts import SearchErrorCode


@dataclass(frozen=True)
class SearchServiceError(Exception):
    code: SearchErrorCode
    status_code: int
    message: str
    retryable: bool = False
    retry_after_ms: int | None = None
