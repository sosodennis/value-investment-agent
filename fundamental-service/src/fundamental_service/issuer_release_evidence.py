"""Issuer release evidence checked by the existing signed release canary."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

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
from .sec_integrity import (
    assess_filing_response,
    require_registered_html_resource_scope,
)
from .parser_computation import execution_validation_evidence
from .serialization import canonical_bytes, sha256_digest
from .valuation_requirements import (
    operating_forecast_requirements_profile,
    composite_working_capital_requirements_profile,
)
from .snapshots import SnapshotError
from .inline_xbrl import (
    InlineDocumentSetError,
    InlineDocumentSetInputV1,
    archive_inline_document_names,
)
from pathlib import PurePosixPath
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
        for policy_id, member_hash in (
            (integrity.normalization_policy_id, integrity.archive_member_hash),
            *(
                (item.normalization_policy_id, item.archive_member_hash)
                for item in integrity.inline_documents
            ),
        ):
            require_registered_html_resource_scope(
                normalization_policy_id=policy_id,
                archive_member_hash=member_hash,
                validation_profile_digest=report.validation_profile_digest,
                taxonomy_cache_hash=report.taxonomy_cache_hash,
            )
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
        or integrity.dqc_filing_context != report.dqc_filing_context
        or report.dqc_filing_context is not None
        and (
            report.dqc_filing_context.issuer_id != source.cik
            or report.dqc_filing_context.accession_number != source.accession_number
        )
        or integrity.accession_number != source.accession_number
        or integrity.primary_document_uri != source.uri
        or integrity.captured_at != source.captured_at
        or integrity.raw_content_hash != source.content_hash
        or integrity.parser_input_hash != source.parser_input_hash
        or integrity.normalized_fact_digest != fact_semantic_digest(report)
        or integrity.normalized_fact_count != len(report.facts)
        or integrity.validation_profile_digest != report.validation_profile_digest
        or integrity.validation_engines != report.validation_engines
        or integrity.validation_evidence != execution_validation_evidence(report)
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
    if len(integrity.submission_content_hashes) > 1:
        raise DataReleaseError(
            "DATA_RELEASE_ORIGINAL_DOCUMENT_SET_MISMATCH",
            "all inline members must retain the same complete submission",
        )
    try:
        raw = contents[integrity.raw_content_hash]
        archive = contents[integrity.archive_hash]
        index = contents[integrity.archive_index_hash]
        parser_input = contents[integrity.parser_input_hash]
        submission_source = (
            _RetainedIntegritySource(
                integrity.archive_index_uri.rsplit("/", 1)[0]
                + f"/{integrity.accession_number}.txt",
                contents[integrity.submission_content_hash],
                integrity.accession_number,
            )
            if integrity.submission_content_hash is not None
            else None
        )
        if PurePosixPath(integrity.primary_document_uri).suffix.lower() in {
            ".htm",
            ".html",
            ".xhtml",
        }:
            archive_inline = archive_inline_document_names(archive)
            expected_inline = archive_inline if len(archive_inline) > 1 else ()
            if expected_inline != tuple(
                d.document.filename for d in integrity.inline_documents
            ):
                raise DataReleaseError(
                    "DATA_RELEASE_ORIGINAL_DOCUMENT_SET_MISMATCH",
                    "inline release omits or changes the archive inventory",
                )
        if integrity.inline_documents:
            manifest = InlineDocumentSetInputV1(
                documents=tuple(d.document for d in integrity.inline_documents)
            )
            if canonical_bytes(manifest) != parser_input:
                raise DataReleaseError(
                    "DATA_RELEASE_ORIGINAL_BYTES_MISMATCH",
                    "inline parser input differs from its document set",
                )
            for member in integrity.inline_documents:
                member_raw = contents[member.raw_content_hash]
                member_parser_input = contents[member.document.content_hash]
                member_assessment = assess_filing_response(
                    raw_response=_RetainedIntegritySource(
                        integrity.primary_document_uri.rsplit("/", 1)[0]
                        + "/"
                        + member.document.filename,
                        member_raw,
                        integrity.accession_number,
                        member.raw_response_headers,
                    ),
                    archive_index=_RetainedIntegritySource(
                        integrity.archive_index_uri, index, integrity.accession_number
                    ),
                    archive=_RetainedIntegritySource(
                        integrity.archive_uri, archive, integrity.accession_number
                    ),
                    submission_source=(
                        _RetainedIntegritySource(
                            integrity.archive_index_uri.rsplit("/", 1)[0]
                            + f"/{integrity.accession_number}.txt",
                            contents[member.submission_content_hash],
                            integrity.accession_number,
                        )
                        if member.submission_content_hash is not None
                        else None
                    ),
                )
                if (
                    member_assessment.normalized_content != member_parser_input
                    or sha256(member_parser_input).hexdigest()
                    != member.document.content_hash
                    or member_assessment.relation != member.integrity_relation
                    or member_assessment.declared_primary_size
                    != member.declared_primary_size
                    or member_assessment.archive_member_name != member.document.filename
                    or len(member_raw) != member.raw_received_size
                    or len(member_assessment.archive_member)
                    != member.archive_member_size
                    or member_assessment.raw_content_hash != member.raw_content_hash
                    or member_assessment.archive_member_hash
                    != member.archive_member_hash
                    or member_assessment.submission_content_hash
                    != member.submission_content_hash
                    or member_assessment.normalization_policy_id
                    != member.normalization_policy_id
                    or member_assessment.normalization_rule_signature
                    != member.normalization_rule_signature
                    or member_assessment.normalization_reason
                    != member.normalization_reason
                    or member_assessment.removed_ranges != member.removed_ranges
                ):
                    raise DataReleaseError(
                        "DATA_RELEASE_ORIGINAL_BYTES_MISMATCH",
                        "inline member bytes differ from their integrity evidence",
                    )
            parser_input = contents[integrity.normalized_content_hash]
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
            submission_source=submission_source,
        )
    except KeyError as error:
        raise DataReleaseError(
            "DATA_RELEASE_ORIGINAL_BYTES_UNAVAILABLE",
            "issuer release must retain raw, parser, archive and index bytes",
        ) from error
    except SnapshotError as error:
        raise DataReleaseError(error.code, str(error)) from error
    except InlineDocumentSetError as error:
        raise DataReleaseError(
            "DATA_RELEASE_ORIGINAL_DOCUMENT_SET_MISMATCH", str(error)
        ) from error
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
        or assessment.submission_content_hash != integrity.submission_content_hash
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
    from .mapping_input_identity import MappingInputDigests

    identities = MappingInputDigests()
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
                input_digests=identities,
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
