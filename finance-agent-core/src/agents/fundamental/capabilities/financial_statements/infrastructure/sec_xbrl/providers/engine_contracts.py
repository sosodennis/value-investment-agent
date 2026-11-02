from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

import pandas as pd


@dataclass(frozen=True)
class XbrlAttachment:
    document: str
    document_type: str
    description: str | None
    content: str


@dataclass(frozen=True)
class XbrlAttachmentBundle:
    ticker: str
    fiscal_year: int | None
    instance_document: str
    attachments: tuple[XbrlAttachment, ...]


ValidationMode = Literal["facts_only", "efm_validate", "efm_dqc_validate"]


@dataclass(frozen=True)
class ArelleValidationProfile:
    mode: ValidationMode = "facts_only"
    disclosure_system: str | None = None
    plugins: tuple[str, ...] = ()
    packages: tuple[str, ...] = ()

    @property
    def validation_enabled(self) -> bool:
        return self.mode != "facts_only"


@dataclass(frozen=True)
class ArelleValidationIssue:
    code: str
    source: str
    severity: str
    message: str
    blocking: bool | None = None
    field_key: str | None = None
    concept: str | None = None
    context_id: str | None = None


@dataclass(frozen=True)
class ArelleRuntimeMetadata:
    mode: str
    disclosure_system: str | None
    plugins: tuple[str, ...]
    packages: tuple[str, ...]
    arelle_version: str | None
    validation_enabled: bool
    runtime_isolation_mode: str | None = None
    runtime_lock_wait_ms: float | None = None


@dataclass(frozen=True)
class ArelleParseResult:
    facts_dataframe: pd.DataFrame
    instance_document: str
    loaded_attachment_count: int
    schema_loaded: bool
    label_loaded: bool
    presentation_loaded: bool
    calculation_loaded: bool
    definition_loaded: bool
    validation_issues: tuple[ArelleValidationIssue, ...] = ()
    runtime_metadata: ArelleRuntimeMetadata | None = None
    parse_latency_ms: float | None = None


class IArelleXbrlEngine(Protocol):
    def parse_attachment_bundle(
        self,
        *,
        bundle: XbrlAttachmentBundle,
    ) -> ArelleParseResult: ...
