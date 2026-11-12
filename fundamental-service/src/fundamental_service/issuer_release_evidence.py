"""Issuer release evidence checked by the existing signed release canary."""

from __future__ import annotations

from dataclasses import dataclass

from .arelle_parser import fact_semantic_digest
from .contracts import CanonicalFactV1, QualityStatus, SecIntegrityEvidenceV1
from .data_releases import DataReleaseError, IssuerOperatingReleaseManifestV1
from .facts import (
    CanonicalMappingV1,
    canonical_fact_digest,
    is_consolidated_fact,
    resolve_canonical_facts,
    select_fact_groups,
)
from .original_issuer import IssuerOperatingSourceV1, OriginalIssuerEvidenceV1
from .regulatory_validation import require_sec_validation_evidence
from .sec_rebuild import parsed_facts_to_candidates
from .sec_integrity import assess_filing_response
from .serialization import sha256_digest
from .valuation_requirements import (
    operating_forecast_requirements_profile,
    composite_working_capital_requirements_profile,
)
from .snapshots import SnapshotError
from .working_capital import working_capital_policy_digest


def require_issuer_release_profile(manifest: IssuerOperatingReleaseManifestV1) -> None:
    if any(
        item.policy_digest != working_capital_policy_digest()
        for item in manifest.working_capital_inputs
    ):
        raise DataReleaseError(
            "DATA_RELEASE_WORKING_CAPITAL_POLICY_MISMATCH",
            "composite inputs require the installed versioned accounting policy digest",
        )
    profile = (
        composite_working_capital_requirements_profile(manifest.model_id)
        if manifest.working_capital_inputs
        else operating_forecast_requirements_profile(manifest.model_id)
    )
    if (
        manifest.required_fields != profile.required_fact_fields
        or manifest.requirements_profile_digest != profile.digest
        or any(
            item.mapping_version != manifest.mapping_version
            for item in manifest.working_capital_inputs
        )
    ):
        raise DataReleaseError(
            "DATA_RELEASE_OPERATING_PROFILE_MISMATCH",
            "issuer releases require the complete pinned operating profile",
        )


def verify_original_integrity(
    original: OriginalIssuerEvidenceV1,
    integrity: SecIntegrityEvidenceV1,
    *,
    parser_version: str,
) -> None:
    source, report = original.source, original.report
    try:
        require_sec_validation_evidence(report)
    except SnapshotError as error:
        raise DataReleaseError(error.code, str(error)) from error
    if report.blocking_finding_codes():
        raise DataReleaseError(
            "DATA_RELEASE_REGULATORY_BLOCKED",
            "original regulatory findings block issuer release",
        )
    if source.http_status != 200:
        raise DataReleaseError(
            "DATA_RELEASE_SOURCE_RECEIPT_UNAVAILABLE",
            "issuer release requires a retained successful original source receipt",
        )
    if (
        integrity.quality_decision != "pass"
        or integrity.accession_number != source.accession_number
        or integrity.primary_document_uri != source.uri
        or integrity.captured_at != source.captured_at
        or integrity.raw_content_hash != source.content_hash
        or integrity.parser_input_hash != source.parser_input_hash
        or integrity.normalized_fact_digest != fact_semantic_digest(report)
        or integrity.normalized_fact_count != len(report.facts)
        or integrity.validation_profile_digest != report.validation_profile_digest
        or integrity.validation_engines != report.validation_engines
        or integrity.validation_evidence != report.validation_evidence
        or integrity.taxonomy_manifest_hash != report.taxonomy_cache_hash
        or integrity.arelle_version != report.parser_version
        or integrity.efm_profile != report.validation_profile.efm_profile
        or integrity.dqc_version != report.validation_profile.dqc_version
        or integrity.xule_version != report.validation_profile.xule_version
        or parser_version
        not in {report.parser_version, f"arelle-release=={report.parser_version}"}
    ):
        raise DataReleaseError(
            "DATA_RELEASE_ORIGINAL_INTEGRITY_MISMATCH",
            "issuer release differs from its exact validated original",
        )


@dataclass(frozen=True)
class _RetainedIntegritySource:
    uri: str
    content: bytes
    accession_number: str
    response_headers: tuple[tuple[str, str], ...] = ()


def verify_original_bytes(
    integrity: SecIntegrityEvidenceV1, contents: dict[str, bytes]
) -> None:
    """Replay the ingestion byte policy without inventing acquisition receipts."""
    try:
        raw = contents[integrity.raw_content_hash]
        archive = contents[integrity.archive_hash]
        index = contents[integrity.archive_index_hash]
        parser_input = contents[integrity.parser_input_hash]
        assessment = assess_filing_response(
            raw_response=_RetainedIntegritySource(
                integrity.primary_document_uri,
                raw,
                integrity.accession_number,
                integrity.raw_response_headers,
            ),
            archive_index=_RetainedIntegritySource(
                integrity.archive_index_uri, index, integrity.accession_number
            ),
            archive=_RetainedIntegritySource(
                integrity.archive_uri, archive, integrity.accession_number
            ),
        )
    except KeyError as error:
        raise DataReleaseError(
            "DATA_RELEASE_ORIGINAL_BYTES_UNAVAILABLE",
            "issuer release must retain raw, parser, archive and index bytes",
        ) from error
    except SnapshotError as error:
        raise DataReleaseError(error.code, str(error)) from error
    if (
        assessment.relation != integrity.integrity_relation
        or assessment.normalized_content != parser_input
        or assessment.declared_primary_size != integrity.declared_primary_size
        or assessment.archive_member_name != integrity.archive_member_name
        or len(raw) != integrity.raw_received_size
        or len(archive) != integrity.archive_size
        or len(assessment.archive_member) != integrity.archive_member_size
        or len(parser_input) != integrity.normalized_content_size
        or assessment.archive_member_hash != integrity.archive_member_hash
        or assessment.normalization_policy_id != integrity.normalization_policy_id
        or assessment.normalization_rule_signature
        != integrity.normalization_rule_signature
        or assessment.normalization_reason != integrity.normalization_reason
        or assessment.removed_ranges != integrity.removed_ranges
    ):
        raise DataReleaseError(
            "DATA_RELEASE_ORIGINAL_BYTES_MISMATCH",
            "retained SEC bytes do not reproduce their declared integrity evidence",
        )


def original_rebuilt_facts(
    snapshot: IssuerOperatingSourceV1, mappings: dict[str, CanonicalMappingV1]
) -> tuple[CanonicalFactV1, ...]:
    """Use the ingestion mapper and selector; no caller-authored normalization."""
    facts = []
    for original in snapshot.originals:
        for mapping in sorted(mappings.values(), key=lambda item: item.decision_id):
            if (
                mapping.accounting_rules is not None
                and mapping.accounting_rules.accession_number
                != original.source.accession_number
            ):
                continue
            candidates = parsed_facts_to_candidates(
                original.report,
                source=original.source,
                issuer_id=snapshot.identity.issuer_id,
                normalized_field=mapping.normalized_field,
                mapping=mapping,
                security_id=None,
            )
            for selection in select_fact_groups(
                candidates, snapshot.valuation_timestamp
            ):
                if selection.fact is not None:
                    facts.append(
                        selection.fact.model_copy(
                            update={
                                "quality": QualityStatus.VERIFIED
                                if mapping.status == "approved"
                                and mapping.confidence == "high"
                                else QualityStatus.PROVISIONAL
                            }
                        )
                    )
    periods: dict[tuple[str, str, str, str], list[CanonicalFactV1]] = {}
    for fact in facts:
        key = (
            fact.normalized_field,
            fact.period_start.isoformat() if fact.period_start else "",
            fact.period_end.isoformat() if fact.period_end else "",
            fact.instant.isoformat() if fact.instant else "",
        )
        periods.setdefault(key, []).append(fact)
    resolved: list[CanonicalFactV1] = []
    for key, period_candidates in sorted(periods.items()):
        if not any(is_consolidated_fact(fact) for fact in period_candidates):
            continue
        resolved.extend(
            resolve_canonical_facts(
                period_candidates,
                snapshot=snapshot,
                valuation_timestamp=snapshot.valuation_timestamp,
                required_fields=(key[0],),
            )
        )
    return tuple(sorted(resolved, key=lambda item: (item.fact_id, sha256_digest(item))))


def require_original_fact_membership(
    snapshot: IssuerOperatingSourceV1,
    facts: tuple[CanonicalFactV1, ...],
    mappings: dict[str, CanonicalMappingV1],
) -> None:
    rebuilt = {
        canonical_fact_digest(fact)
        for fact in original_rebuilt_facts(snapshot, mappings)
    }
    if {canonical_fact_digest(fact) for fact in facts} != rebuilt:
        raise DataReleaseError(
            "DATA_RELEASE_ORIGINAL_FACT_MISMATCH",
            "released issuer facts must retain the complete shared original-source normalization",
        )
