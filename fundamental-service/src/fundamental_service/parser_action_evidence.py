"""Storage-owned parser result verification, independently scoped by each consumer."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from collections.abc import Iterable

from .arelle_parser import ArelleParseReportV1, fact_semantic_digest
from .artifact_evidence import read_retained_artifact, require_retained_artifact
from .mapping_input_storage import MappingInputReader
from .data_releases import ArtifactRefV1
from .original_issuer import (
    OriginalIssuerEvidenceChecks,
    OriginalIssuerEvidenceV1,
    canonical_original_report,
)
from .parser_action_contracts import (
    ParserActionInputV1,
    ParserActionInputV2,
    ParserActionInputV3,
    ParserActionResult,
    ParserActionDeliveryV2,
    parser_action_markers,
    read_action_result,
)
from .parser_action_identity import ParserBuildChecks, IncompleteParserClosure
from .regulatory_validation import (
    bind_dqc_filing_context,
    require_sec_validation_evidence,
)
from .replay import ArtifactRecordV1
from .serialization import canonical_bytes
from .snapshots import SnapshotError


def require_current_parser_action_refs(
    references: Iterable[ArtifactRefV1],
    *,
    artifacts: MappingInputReader,
    build_checks: ParserBuildChecks | None = None,
) -> None:
    """Recheck consumed action bytes and live metadata at successful output.

    The caller already verified the action's semantic closure. Rewalk its
    retained references rather than an evictable cache of that verification.
    """
    records: dict[str, ArtifactRecordV1] = {}
    if build_checks is None:
        build_checks = ParserBuildChecks()
    for ref in references:
        if ref.role not in {
            "sec-parser-action-result-v1",
            "sec-parser-action-report-v1",
            "sec-parser-action-result-v2",
            "sec-parser-action-delivery-v2",
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
            if ref.role == "sec-parser-action-result-v2":
                request = read_action_result(raw).request
                try:
                    if (
                        not isinstance(
                            request, (ParserActionInputV2, ParserActionInputV3)
                        )
                        or request.build != build_checks.current()
                    ):
                        raise SnapshotError(
                            "PARSER_ACTION_EVIDENCE_INVALID", "parser build differs"
                        )
                except (IncompleteParserClosure, OSError) as error:
                    raise SnapshotError(
                        "PARSER_ACTION_EVIDENCE_INVALID", "parser build changed"
                    ) from error
            records[ref.artifact_id] = record
    for identity, record in records.items():
        if artifacts.get(identity) != record:
            raise SnapshotError(
                "PARSER_ACTION_EVIDENCE_INVALID", "action metadata changed"
            )
    build_checks.verify()


def read_parser_action_result(
    artifact_id: str,
    *,
    artifacts: MappingInputReader,
) -> tuple[ArelleParseReportV1, ParserActionResult, ArtifactRecordV1]:
    record = artifacts.get(artifact_id)
    raw = artifacts.read(artifact_id)
    result = read_action_result(raw)
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
    from .fiscal_source_closure import _FiscalSourceArtifactRead

    if isinstance(artifacts, _FiscalSourceArtifactRead):
        artifacts._parser_report_edge(result)
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
        or report.execution_evidence
        or report.identity_protocol is not None
        or any(
            value.startswith(("sec-parser-action-", "sec-parser-computation-"))
            for value in report.validation_evidence
        )
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
    original_checks: OriginalIssuerEvidenceChecks | None = None,
    build_checks: ParserBuildChecks | None = None,
) -> tuple[tuple[str, ArtifactRecordV1], ...]:
    """Independent consumers recheck immutable action provenance and live status.

    Call through the consumer's evidence read scope so the action result and body
    also remain in its consumed dependency set until publication.
    """
    report = original_evidence.report
    action_evidence = (*report.validation_evidence, *report.execution_evidence)
    markers = parser_action_markers(action_evidence)
    # Claim validity and raw-body equivalence are separate predicates. Reuse
    # this consumer's full claim check, not a producer's claim or a bool flag.
    if original_checks is None:
        original_checks = OriginalIssuerEvidenceChecks()
    try:
        original_checks.validate(original_evidence)
    except ValueError as error:
        raise SnapshotError(
            "PARSER_ACTION_EVIDENCE_INVALID", "normalized report differs"
        ) from error
    if not markers:
        return ()
    consumed = []
    if build_checks is None:
        build_checks = ParserBuildChecks()
    for version, representation, key, digest, binding_digest in markers:
        artifact_id = f"sec-parser-action-result-{version}:{key}:{digest}"
        original, result, record = read_parser_action_result(
            artifact_id,
            artifacts=artifacts,
        )
        body_id = f"sec-parser-action-report-v1:{result.report_content_hash}"
        references = [
            (artifact_id, f"sec-parser-action-result-{version}"),
            (body_id, "sec-parser-action-report-v1"),
        ]
        if isinstance(result.request, (ParserActionInputV2, ParserActionInputV3)):
            if version != "v2" or binding_digest is None:
                raise SnapshotError(
                    "PARSER_ACTION_EVIDENCE_INVALID", "action protocol differs"
                )
            binding_id = f"sec-parser-action-delivery-v2:{binding_digest}"
            binding_record = artifacts.get(binding_id)
            binding_raw = artifacts.read(binding_id)
            binding = ParserActionDeliveryV2.model_validate_json(binding_raw)
            try:
                expected_build = build_checks.current()
            except (IncompleteParserClosure, OSError) as error:
                raise SnapshotError(
                    "PARSER_ACTION_EVIDENCE_INVALID",
                    "current parser build is unavailable",
                ) from error
            if (
                result.request.build != expected_build
                or binding.build != expected_build
                or binding.delivery_revision != delivery_revision
                or binding.action_key != key
                or binding.result_artifact_id != artifact_id
                or binding.report_content_hash != result.report_content_hash
                or binding_record.status != "valid"
                or binding_record.retention != "evidence"
                or binding_record.media_type != "application/json"
                or binding_record.content_hash != binding_digest
                or hashlib.sha256(binding_raw).hexdigest() != binding_digest
                or binding_raw != canonical_bytes(binding)
                or binding_record.dependency_hashes
                != tuple(sorted({key, result.report_content_hash, digest}))
            ):
                raise SnapshotError(
                    "PARSER_ACTION_EVIDENCE_INVALID", "parser delivery binding differs"
                )
            references.append((binding_id, "sec-parser-action-delivery-v2"))
        for identity, role in references:
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
            or (
                isinstance(result.request, ParserActionInputV1)
                and result.request.delivery_revision != delivery_revision
            )
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
                        next(
                            value
                            for value in action_evidence
                            if value.startswith(
                                f"sec-parser-action-{version}:normalized:"
                            )
                        ),
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
                            for v in action_evidence
                            if v.startswith(
                                (
                                    "sec-parser-action-v1:archive:",
                                    "sec-parser-action-v2:archive:",
                                )
                            )
                        ),
                    )
                }
            )
            expected = canonical_original_report(
                original,
                source=original_evidence.source,
                policy_version=original_evidence.policy_version,
            )
            if expected != report or canonical_bytes(
                expected.model_dump(mode="json")
            ) != canonical_bytes(report.model_dump(mode="json")):
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
    build_checks.verify()
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
