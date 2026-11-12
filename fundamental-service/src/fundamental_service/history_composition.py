"""Compose retained original SEC snapshots without fetching or changing facts."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import ValidationError

from .contracts import (
    FiscalPeriodSelectorV1,
    QualityStatus,
    SecHistoryComponentV1,
    SecHistoryIntegrityEvidenceV1,
    SecIntegrityEvidenceV1,
    SourceRole,
    SourceSnapshotV1,
)
from .serialization import sha256_digest
from .snapshots import SnapshotError, SnapshotRepository


class HistorySnapshotReader(Protocol):
    def get(self, snapshot_id: str) -> SourceSnapshotV1: ...


def _verify_original(
    component: SourceSnapshotV1, valuation_timestamp: datetime
) -> SecIntegrityEvidenceV1:
    integrity = component.sec_integrity_evidence
    filing_sources = tuple(
        source
        for source in component.source_records
        if source.source_id == "sec-filing"
    )
    archive_sources = tuple(
        source
        for source in component.source_records
        if source.source_id == "sec-filing-archive"
    )
    submission_sources = tuple(
        source
        for source in component.source_records
        if source.source_id == "sec-filing-submission"
    )
    if (
        not isinstance(integrity, SecIntegrityEvidenceV1)
        or integrity.quality_decision != "pass"
        or component.coverage_status is not QualityStatus.VERIFIED
        or component.valuation_timestamp > valuation_timestamp
        or len(filing_sources) != 1
        or len(archive_sources) != 1
        or len(submission_sources) > 1
        or any(
            source.role is SourceRole.FILING
            and source.source_id
            not in {"sec-filing", "sec-filing-archive", "sec-filing-submission"}
            for source in component.source_records
        )
        or any(
            source.role is not SourceRole.ACQUISITION
            and source.available_at > component.valuation_timestamp
            for source in component.source_records
        )
    ):
        raise SnapshotError(
            "HISTORY_ORIGINAL_UNAVAILABLE",
            "history requires an available, independently verified original",
        )
    source = filing_sources[0]
    if (
        source.role is not SourceRole.FILING
        or source.accession_number != integrity.accession_number
        or source.content_hash != integrity.raw_content_hash
        or source.parser_input_hash != integrity.parser_input_hash
        or source.uri != integrity.primary_document_uri
        or source.is_amendment
        or source.form != "10-K"
        or integrity.captured_at > component.captured_at
        or integrity.validation_profile_digest != component.validation_profile_digest
    ):
        raise SnapshotError(
            "HISTORY_ORIGINAL_INTEGRITY_MISMATCH",
            "original source is not bound to its own integrity evidence",
        )
    archive = archive_sources[0]
    if (
        archive.role is not SourceRole.FILING
        or archive.accession_number != integrity.accession_number
        or archive.content_hash != integrity.archive_hash
        or archive.uri != integrity.archive_uri
        or archive.received_size != integrity.archive_size
        or archive.available_at != source.available_at
        or archive.filed_at != source.filed_at
        or archive.is_amendment
        or archive.form != "10-K"
        or not 200 <= archive.http_status < 300
    ):
        raise SnapshotError(
            "HISTORY_ORIGINAL_INTEGRITY_MISMATCH",
            "original archive is not bound to its own integrity evidence",
        )
    if submission_sources:
        submission = submission_sources[0]
        submission_prefix = integrity.primary_document_uri.rsplit("/", 1)[0] + "/"
        if (
            submission.role is not SourceRole.FILING
            or submission.accession_number != integrity.accession_number
            or submission.uri != f"{submission_prefix}{integrity.accession_number}.txt"
            or submission.available_at != source.available_at
            or submission.filed_at != source.filed_at
            or submission.form != source.form
            or submission.is_amendment != source.is_amendment
            or not 200 <= submission.http_status < 300
        ):
            raise SnapshotError(
                "HISTORY_ORIGINAL_INTEGRITY_MISMATCH",
                "original full submission is not bound to its filing",
            )
    return integrity


def verify_history_components(
    snapshot: SourceSnapshotV1, repository: HistorySnapshotReader
) -> tuple[SourceSnapshotV1, ...]:
    """Read each referenced original; the aggregate cannot vouch for itself."""
    evidence = snapshot.sec_integrity_evidence
    if not isinstance(evidence, SecHistoryIntegrityEvidenceV1):
        return ()
    try:
        components = tuple(
            repository.get(reference.snapshot_id) for reference in evidence.components
        )
    except SnapshotError as error:
        raise SnapshotError(
            "HISTORY_COMPONENT_UNAVAILABLE",
            "history original is unavailable; restore the retained evidence",
            retryable=error.retryable,
        ) from error
    except ValueError as error:
        raise SnapshotError(
            "HISTORY_COMPONENT_INVALID", "history original failed manifest validation"
        ) from error
    for reference, component in zip(evidence.components, components, strict=True):
        _verify_original(component, snapshot.valuation_timestamp)
        if (
            component.manifest_digest != reference.manifest_digest
            or component.sec_integrity_evidence != reference.integrity
            or component.identity != snapshot.identity
            or component.valuation_timestamp > snapshot.valuation_timestamp
            or component.captured_at > snapshot.captured_at
            or component.coverage_status is not QualityStatus.VERIFIED
            or component.parser_version != snapshot.parser_version
            or component.policy_version != snapshot.policy_version
            or component.taxonomy_manifest_id != snapshot.taxonomy_manifest_id
            or component.validation_profile_id != snapshot.validation_profile_id
            or component.validation_profile_digest != snapshot.validation_profile_digest
        ):
            raise SnapshotError(
                "HISTORY_COMPONENT_MISMATCH",
                "history component does not match its retained original",
            )
    sources = tuple(
        sorted(
            {
                sha256_digest(source): source
                for component in components
                for source in component.source_records
            }.values(),
            key=lambda source: (source.source_id, source.uri, source.content_hash),
        )
    )
    if snapshot.source_records != sources:
        raise SnapshotError(
            "HISTORY_SOURCE_MISMATCH",
            "history sources do not match its original snapshots",
        )
    return components


def compose_original_history(
    repository: SnapshotRepository,
    snapshot_ids: tuple[str, ...],
    *,
    valuation_timestamp: datetime,
    fiscal_period_selector: FiscalPeriodSelectorV1,
) -> SourceSnapshotV1:
    """Publish one deterministic source view; the formal composer judges sufficiency."""
    if not 2 <= len(snapshot_ids) <= 6 or len(set(snapshot_ids)) != len(snapshot_ids):
        raise SnapshotError(
            "HISTORY_COMPONENTS_INVALID",
            "history requires two to six distinct original snapshots",
        )
    if valuation_timestamp.tzinfo is None or valuation_timestamp.utcoffset() is None:
        raise SnapshotError(
            "HISTORY_TIMESTAMP_INVALID", "history valuation time must be zoned"
        )
    components = tuple(repository.get(key) for key in sorted(snapshot_ids))
    first = components[0]
    references = []
    for component in components:
        integrity = _verify_original(component, valuation_timestamp)
        references.append(
            SecHistoryComponentV1(
                snapshot_id=component.snapshot_id,
                manifest_digest=component.manifest_digest,
                integrity=integrity,
            )
        )
    try:
        evidence = SecHistoryIntegrityEvidenceV1(components=tuple(references))
    except ValidationError as error:
        raise SnapshotError(
            "HISTORY_COMPONENTS_INVALID", "history originals are not distinct"
        ) from error
    sources = tuple(
        sorted(
            {
                sha256_digest(source): source
                for component in components
                for source in component.source_records
            }.values(),
            key=lambda source: (source.source_id, source.uri, source.content_hash),
        )
    )
    payload = {
        "contract_version": "fundamental.v1",
        "identity": first.identity,
        "valuation_timestamp": valuation_timestamp,
        "fiscal_period_selector": fiscal_period_selector,
        "resolved_fiscal_periods": (),
        "captured_at": max(component.captured_at for component in components),
        "source_records": sources,
        "taxonomy_manifest_id": first.taxonomy_manifest_id,
        "acquisition_key": None,
        "validation_profile_id": first.validation_profile_id,
        "validation_profile_digest": first.validation_profile_digest,
        "parser_version": first.parser_version,
        "policy_version": first.policy_version,
        "coverage_status": QualityStatus.VERIFIED,
        "issues": (),
        "sec_integrity_evidence": evidence,
    }
    digest = sha256_digest(payload)
    try:
        snapshot = SourceSnapshotV1.model_validate(
            {**payload, "snapshot_id": f"history-{digest}", "manifest_digest": digest}
        )
    except ValidationError as error:
        raise SnapshotError(
            "HISTORY_MANIFEST_INVALID", "history originals cannot share one manifest"
        ) from error
    verify_history_components(snapshot, repository)
    repository.publish(snapshot)
    return snapshot
