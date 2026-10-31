from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ImportItemStatus = Literal[
    "queued",
    "validating",
    "retry_wait",
    "imported",
    "duplicate",
    "invalid",
    "unavailable",
    "expired",
]

ImportBatchStatus = Literal[
    "queued", "processing", "completed", "completed_with_errors"
]


@dataclass(frozen=True)
class KeyImportInput:
    source_line: int
    label: str
    api_key: str = field(repr=False)


@dataclass(frozen=True)
class ClaimedKeyImportItem:
    id: str
    batch_id: str
    user_id: str
    source_line: int
    label: str
    fingerprint: str
    suffix: str
    api_key: str = field(repr=False)
    attempts: int
    worker_id: str


@dataclass(frozen=True)
class KeyImportItemSnapshot:
    source_line: int
    label: str
    suffix: str | None
    status: ImportItemStatus
    error_code: str | None
    attempts: int
    retryable: bool


@dataclass(frozen=True)
class KeyImportSnapshot:
    id: str
    status: ImportBatchStatus
    total_count: int
    processed_count: int
    imported_count: int
    duplicate_count: int
    invalid_count: int
    retryable_count: int
    created_at: str
    updated_at: str
    items: tuple[KeyImportItemSnapshot, ...] = ()
