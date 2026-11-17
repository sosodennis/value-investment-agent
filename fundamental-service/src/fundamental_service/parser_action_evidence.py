"""Storage-owned parser result verification, independently scoped by each consumer."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime

from .arelle_parser import ArelleParseReportV1, fact_semantic_digest
from .artifact_evidence import read_retained_artifact, require_retained_artifact
from .mapping_input_storage import MappingInputReader
from .data_releases import ArtifactRefV1
from .original_issuer import OriginalIssuerEvidenceV1, evaluate_original_issuer
from .parser_action_contracts import ParserActionResultV1, parser_action_markers
from .regulatory_validation import (
    bind_dqc_filing_context,
    require_sec_validation_evidence,
)
from .replay import ArtifactRecordV1
from .serialization import canonical_bytes
from .snapshots import SnapshotError


def require_current_parser_action_refs(
    references: Iterable[ArtifactRefV1], *, artifacts: MappingInputReader
) -> None:
    """Recheck consumed action bytes and live metadata at successful output.

    The caller already verified the action's semantic closure. Rewalk its
    retained references rather than an evictable cache of that verification.
    """
    records: dict[str, ArtifactRecordV1] = {}
    for ref in references:
        if ref.role not in {
            "sec-parser-action-result-v1",
            "sec-parser-action-report-v1",
        }:
            continue
        record = require_retained_artifact(artifacts, ref)
        if ref.artifact_id in records and records[ref.artifact_id] != record:
            raise SnapshotError(
                "PARSER_ACTION_EVIDENCE_INVALID", "action metadata changed"
            )
        if ref.artifact_id not in records:
            raw = read_retained_artifact(artifacts, ref)
            if hashlib.sha256(raw).hexdigest() != ref.content_hash:
                raise SnapshotError(
                    "PARSER_ACTION_EVIDENCE_INVALID", "action bytes changed"
                )
            records[ref.artifact_id] = record
    for identity, record in records.items():
        if artifacts.get(identity) != record:
            raise SnapshotError(
                "PARSER_ACTION_EVIDENCE_INVALID", "action metadata changed"
            )


def read_parser_action_result(
    artifact_id: str,
    *,
    artifacts: MappingInputReader,
) -> tuple[ArelleParseReportV1, ParserActionResultV1, ArtifactRecordV1]:
    record = artifacts.get(artifact_id)
    raw = artifacts.read(artifact_id)
    result = ParserActionResultV1.model_validate_json(raw)
    request = result.request
    if (
        record.status != "valid"
        or record.retention != "evidence"
        or record.media_type != "application/json"
        or hashlib.sha256(raw).hexdigest() != record.content_hash
        or raw != canonical_bytes(result)
        or result.artifact_id != artifact_id
        or record.dependency_hashes
        != tuple(sorted({request.digest, result.report_content_hash}))
    ):
        raise SnapshotError(
            "PARSER_ACTION_EVIDENCE_INVALID", "parser action result differs"
        )
    body_id = f"sec-parser-action-report-v1:{result.report_content_hash}"
    body_record = artifacts.get(body_id)
    body = artifacts.read(body_id)
    if (
        body_record.status != "valid"
        or body_record.retention != "evidence"
        or body_record.media_type != "application/json"
        or body_record.content_hash != result.report_content_hash
        or hashlib.sha256(body).hexdigest() != result.report_content_hash
        or artifacts.get(body_id) != body_record
    ):
        raise SnapshotError("PARSER_ACTION_EVIDENCE_INVALID", "parser body differs")
    report = ArelleParseReportV1.model_validate_json(body)
    if (
        body != canonical_bytes(report.model_dump(mode="json"))
        or report.validation_profile_digest != request.profile_digest
        or report.taxonomy_version != request.taxonomy_version
        or report.taxonomy_cache_hash != dict(request.resources).get("taxonomy")
        or report.source_content_hash != request.source_content_hash
        or report.dqc_filing_context is not None
        or report.parsed_at.tzinfo is None
        or report.parsed_at > datetime.now(UTC)
    ):
        raise SnapshotError(
            "PARSER_ACTION_EVIDENCE_INVALID", "parser body identity differs"
        )
    require_sec_validation_evidence(report)
    if artifacts.get(artifact_id) != record:
        raise SnapshotError(
            "PARSER_ACTION_EVIDENCE_INVALID", "parser action metadata changed"
        )
    return report, result, record


def require_parser_action_evidence(
    original_evidence: OriginalIssuerEvidenceV1,
    *,
    artifacts: MappingInputReader,
    delivery_revision: str,
    evidence_refs: tuple[ArtifactRefV1, ...] | None = None,
) -> tuple[tuple[str, ArtifactRecordV1], ...]:
    """Independent consumers recheck immutable action provenance and live status.

    Call through the consumer's evidence read scope so the action result and body
    also remain in its consumed dependency set until publication.
    """
    report = original_evidence.report
    markers = parser_action_markers(report.validation_evidence)
    if not markers:
        return ()
    consumed = []
    for representation, key, digest in markers:
        artifact_id = f"sec-parser-action-result-v1:{key}:{digest}"
        original, result, record = read_parser_action_result(
            artifact_id,
            artifacts=artifacts,
        )
        body_id = f"sec-parser-action-report-v1:{result.report_content_hash}"
        for identity, role in (
            (artifact_id, "sec-parser-action-result-v1"),
            (body_id, "sec-parser-action-report-v1"),
        ):
            metadata = artifacts.get(identity)
            if metadata.status != "valid":
                raise SnapshotError(
                    "PARSER_ACTION_EVIDENCE_INVALID", "action metadata changed"
                )
            if (
                evidence_refs is not None
                and ArtifactRefV1(
                    artifact_id=identity,
                    content_hash=metadata.content_hash,
                    media_type=metadata.media_type,
                    role=role,
                )
                not in evidence_refs
            ):
                raise SnapshotError(
                    "PARSER_ACTION_EVIDENCE_INVALID", "action closure is absent"
                )
            consumed.append((identity, metadata))
        if (
            result.request.digest != key
            or result.request.delivery_revision != delivery_revision
            or result.request.representation != representation
            or original.parser_version != report.parser_version
            or original.validation_profile_digest != report.validation_profile_digest
            or original.taxonomy_cache_hash != report.taxonomy_cache_hash
            or original.taxonomy_version != report.taxonomy_version
        ):
            raise SnapshotError(
                "PARSER_ACTION_EVIDENCE_INVALID", "parser action differs"
            )
        if representation == "normalized":
            original = original.model_copy(
                update={
                    "validation_evidence": (
                        *original.validation_evidence,
                        result.evidence_marker(),
                    )
                }
            )
            if report.dqc_filing_context is not None:
                original = bind_dqc_filing_context(original, report.dqc_filing_context)
            original = original.model_copy(
                update={
                    "validation_evidence": (
                        *original.validation_evidence,
                        *(
                            v
                            for v in report.validation_evidence
                            if v.startswith("sec-parser-action-v1:archive:")
                        ),
                    )
                }
            )
            expected = evaluate_original_issuer(
                original,
                source=original_evidence.source,
                decision_at=original_evidence.decision_at,
            )
            if expected != original_evidence:
                raise SnapshotError(
                    "PARSER_ACTION_EVIDENCE_INVALID", "normalized report differs"
                )
        else:
            if report.dqc_filing_context is not None:
                original = bind_dqc_filing_context(original, report.dqc_filing_context)
            if fact_semantic_digest(original) != fact_semantic_digest(
                report
            ) or _finding_signature(original) != _finding_signature(report):
                raise SnapshotError(
                    "PARSER_ACTION_EVIDENCE_INVALID", "archive semantics differ"
                )
        if artifacts.get(artifact_id) != record:
            raise SnapshotError(
                "PARSER_ACTION_EVIDENCE_INVALID", "action metadata changed"
            )
    for identity, metadata in consumed:
        if artifacts.get(identity) != metadata:
            raise SnapshotError(
                "PARSER_ACTION_EVIDENCE_INVALID", "action metadata changed"
            )
    return tuple(consumed)


def _finding_signature(
    report: ArelleParseReportV1,
) -> tuple[tuple[str, str, str, str, bool], ...]:
    blocking = set(report.blocking_finding_codes())
    return tuple(
        sorted(
            (
                f.code,
                f.severity,
                f.rule_severity or "",
                f.rule_effective_date.isoformat() if f.rule_effective_date else "",
                f.code in blocking,
            )
            for f in report.findings
        )
    )
