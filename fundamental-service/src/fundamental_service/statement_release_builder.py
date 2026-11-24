from __future__ import annotations

from typing import Protocol

from .annual_statements import project_annual_statements
from .automatic_data_release import AutomaticDataReleaseRequestV1
from .automatic_mapping_batch import (
    StatementMappingBatchDecisionV1,
    StatementMappingBatchRequestV1,
)
from .command_artifacts import EvidenceArtifactStore
from .contracts import (
    SecIngestionResponseV1,
    SourceSnapshotV1,
)
from .data_releases import (
    ArtifactRefV1,
    AutomaticMappingApprovalV1,
    DataReleaseContentRequestV1,
    DataReleaseError,
    DataReleaseManifestV1,
    FactRefV1,
    MappingRefV1,
    SnapshotRefV1,
)
from .facts import CanonicalFactRepository, canonical_fact_digest
from .mapping_input_storage import read_mapping_batch_input
from .original_preparation import OriginalPreparation
from .registered_statement_rows import (
    primary_statement_scope_evidence,
    statement_cash_basis,
)
from .serialization import canonical_bytes, sha256_digest
from .statement_contracts import (
    DurationStatementPeriodV1,
    StatementAnnualColumnV1,
    StatementAvailableSourceV1,
    StatementFactEvidenceV1,
    StatementProjectionInputV1,
    StatementScopeV1,
    StatementMissingEvidenceV1,
    StatementSourceOutcomeV1,
)
from .statement_profiles import annual_statement_profile, statement_executable_digest
from .statement_releases import (
    STATEMENT_RELEASE_ROLE,
    StatementMappingReader,
    StatementReleaseEnvelopeV1,
    statement_release_namespace,
    unavailable_statement_original,
)
from .statement_mapping_evidence import statement_missing_evidence


class StatementBuilderSnapshots(Protocol):
    def get(self, snapshot_id: str) -> SourceSnapshotV1: ...


def _reference(
    artifacts: EvidenceArtifactStore, artifact_id: str, role: str
) -> ArtifactRefV1:
    record = artifacts.get(artifact_id)
    return ArtifactRefV1(
        artifact_id=record.artifact_id,
        content_hash=record.content_hash,
        media_type=record.media_type,
        role=role,
    )


def build_statement_release(
    original_preparation: ArtifactRefV1,
    ingestions: tuple[SecIngestionResponseV1, ...],
    *,
    originals: OriginalPreparation,
    snapshots: StatementBuilderSnapshots,
    facts: CanonicalFactRepository,
    mappings: StatementMappingReader,
    artifacts: EvidenceArtifactStore,
    source_revision: str,
    mapping_version: str,
) -> AutomaticDataReleaseRequestV1:
    prepared, validations = originals.read_with_validations(
        original_preparation.artifact_id
    )
    if (
        originals.reference(original_preparation.artifact_id, original_preparation.role)
        != original_preparation
    ):
        raise DataReleaseError(
            "STATEMENT_RELEASE_PREPARATION_MISMATCH",
            "original preparation reference differs",
        )
    profile = annual_statement_profile(executable_digest=statement_executable_digest())
    by_accession: dict[str, SecIngestionResponseV1] = {}
    for ingestion in ingestions:
        accessions = {
            source.accession_number
            for source in ingestion.source_evidence
            if source.source_id == "sec-filing"
        }
        if len(accessions) != 1 or None in accessions:
            raise DataReleaseError(
                "STATEMENT_INGESTION_SOURCE_MISMATCH",
                "statement ingestion must bind exactly one original",
            )
        accession = next(iter(accessions))
        assert accession is not None
        if accession in by_accession:
            raise DataReleaseError(
                "STATEMENT_INGESTION_SOURCE_MISMATCH",
                "statement ingestion originals must be distinct",
            )
        by_accession[accession] = ingestion
    refs = [original_preparation, prepared.request.annual]
    columns: list[StatementAnnualColumnV1] = []
    outcomes: list[StatementSourceOutcomeV1] = []
    evidence: list[StatementFactEvidenceV1] = []
    snapshot_refs: list[SnapshotRefV1] = []
    reviews: dict[str, AutomaticMappingApprovalV1] = {}
    used_mappings = {}
    scope = None
    cutoff = None
    captured = []
    missing_evidence: list[StatementMissingEvidenceV1] = []
    seen = set()
    for item, validation in zip(prepared.filings, validations, strict=True):
        request = validation.request
        if request.runtime.declared_source_revision != source_revision:
            raise DataReleaseError(
                "STATEMENT_RELEASE_REVISION_MISMATCH",
                "statement originals require the declared installed source revision",
            )
        cutoff = request.valuation_timestamp
        filing = request.filing
        seen.add(filing.accession_number)
        outcome_ref = originals.reference(
            validation.artifact_id, "sec-original-validation-v1"
        )
        refs.append(outcome_ref)
        if item.issue_codes:
            outcome, column = unavailable_statement_original(
                filing, outcome_ref, item.issue_codes
            )
            outcomes.append(outcome)
            columns.append(column)
            if filing.accession_number in by_accession:
                raise DataReleaseError(
                    "STATEMENT_INGESTION_SOURCE_MISMATCH",
                    "failed original preparation cannot carry published statement facts",
                )
            continue
        result = by_accession.get(filing.accession_number)
        if (
            result is None
            or result.snapshot_id is None
            or not result.canonical_fact_ids
            or result.mapping_evidence_ref is None
            or validation.original is None
            or item.identity is None
        ):
            raise DataReleaseError(
                "STATEMENT_INGESTION_REQUIRED",
                "every validated selected original requires its canonical statement ingestion outcome",
            )
        snapshot = snapshots.get(result.snapshot_id)
        candidate_scope = StatementScopeV1(
            issuer_id=snapshot.identity.issuer_id,
            security_id=snapshot.identity.security_id,
            security_scope="issuer",
            entity_scope=snapshot.identity.issuer_id,
            currency=snapshot.identity.currency,
            unit="iso4217:" + snapshot.identity.currency,
        )
        if scope is None:
            scope = candidate_scope
        elif scope != candidate_scope:
            raise DataReleaseError(
                "STATEMENT_RELEASE_SOURCE_CONTEXT_MISMATCH",
                "selected statement originals do not share the exact issuer and security scope",
            )
        if (
            snapshot.identity != item.identity
            or result.identity != item.identity
            or result.valuation_timestamp != cutoff
            or result.manifest_digest != snapshot.manifest_digest
        ):
            raise DataReleaseError(
                "STATEMENT_INGESTION_SOURCE_MISMATCH",
                "canonical statement ingestion differs from the original preparation",
            )
        captured.append(snapshot.captured_at)
        batch_ref = _reference(
            artifacts,
            result.mapping_evidence_ref,
            "statement-mapping-batch-decision-v1",
        )
        batch = StatementMappingBatchDecisionV1.model_validate_json(
            artifacts.read(batch_ref.artifact_id)
        )
        batch_input_ref, batch_input = read_mapping_batch_input(
            batch.input_digest, StatementMappingBatchRequestV1, artifacts=artifacts
        )
        if (
            batch.statement_profile != profile
            or batch_input.statement_profile != profile
            or batch_input.original != validation.original
            or batch_input.mapping_version != mapping_version
            or batch_input.source_revision != source_revision
        ):
            raise DataReleaseError(
                "STATEMENT_RELEASE_MAPPING_CONTEXT_MISMATCH",
                "statement mapping outcomes differ from the original and installed profile",
            )
        refs.extend((batch_ref, batch_input_ref, *batch_input.evidence_refs))
        local_reviews = {}
        for role in batch.roles:
            for decision in role.proposal_decisions():
                for reference in (decision.decision, decision.approval):
                    if reference is not None:
                        refs.append(reference)
                if decision.approval is not None:
                    approval = AutomaticMappingApprovalV1.model_validate_json(
                        artifacts.read(decision.approval.artifact_id)
                    )
                    local_reviews[approval.mapping_id] = approval
        local_facts = []
        for fact_id in result.canonical_fact_ids:
            fact = facts.get(fact_id)
            mapping = mappings.get_mapping(fact.mapping_decision_id or "")
            fact_review = local_reviews.get(mapping.decision_id)
            if fact_review is None or mapping.normalized_field not in {
                row.row_id for row in profile.rows
            }:
                raise DataReleaseError(
                    "STATEMENT_RELEASE_MAPPING_CONTEXT_MISMATCH",
                    "canonical statement fact requires its original's approved row mapping",
                )
            reviews[mapping.decision_id] = fact_review
            used_mappings[mapping.decision_id] = mapping
            refs.extend(fact_review.evidence_refs)
            source = next(
                (
                    source
                    for source in snapshot.source_records
                    if source.source_id == "sec-filing"
                    and source.accession_number == filing.accession_number
                    and source.content_hash == validation.original.source.content_hash
                ),
                None,
            )
            if source is None:
                raise DataReleaseError(
                    "STATEMENT_RELEASE_SOURCE_SNAPSHOT_MISMATCH",
                    "statement fact lacks the exact retained original source record",
                )
            evidence.append(
                StatementFactEvidenceV1(
                    fact=fact,
                    mapping=mapping,
                    source=source,
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_manifest_digest=snapshot.manifest_digest,
                    mapping_evidence_refs=(batch_ref, *fact_review.evidence_refs),
                    cash_basis=statement_cash_basis(
                        validation.original, fact.normalized_field, fact.concept
                    ),
                )
            )
            local_facts.append(
                FactRefV1(fact_id=fact.fact_id, fact_digest=canonical_fact_digest(fact))
            )
        fact_refs = tuple(sorted(local_facts, key=lambda ref: ref.fact_id))
        snapshot_refs.append(
            SnapshotRefV1(
                snapshot_id=snapshot.snapshot_id,
                manifest_digest=snapshot.manifest_digest,
                facts=fact_refs,
                fact_set_digest=sha256_digest(fact_refs),
            )
        )
        outcomes.append(
            StatementAvailableSourceV1(
                accession_number=filing.accession_number,
                available_at=filing.accepted_at,
                report_period_end=filing.report_period_end,
                outcome_ref=outcome_ref,
                fact_ids=tuple(sorted(result.canonical_fact_ids)),
            )
        )
        primary_scope = primary_statement_scope_evidence(validation.original, "revenue")
        if primary_scope is None:
            raise DataReleaseError(
                "STATEMENT_ORIGINAL_SCOPE_UNREVIEWED",
                "original annual period is not reviewed",
            )
        periods = tuple(
            (start, end)
            for start, end in primary_scope.annual_periods
            if end == filing.report_period_end
        )
        if len(periods) != 1:
            raise DataReleaseError(
                "STATEMENT_RELEASE_PERIOD_MISMATCH",
                "original primary row does not establish one actual annual duration",
            )
        columns.append(
            StatementAnnualColumnV1(
                fiscal_label=f"FY{filing.report_period_end.year}",
                period=DurationStatementPeriodV1(
                    period_start=periods[0][0], period_end=periods[0][1]
                ),
                original_accession=filing.accession_number,
            )
        )
        missing_evidence.extend(
            statement_missing_evidence(
                batch,
                batch_ref,
                candidate_scope,
                columns[-1],
                {
                    item.fact.normalized_field
                    for item in evidence
                    if item.snapshot_id == snapshot.snapshot_id
                },
            )
        )
    if not by_accession.keys() <= seen or scope is None or cutoff is None:
        raise DataReleaseError(
            "STATEMENT_RELEASE_ORIGINALS_MISMATCH",
            "statement release requires canonical facts from its exact selected originals",
        )
    projection = StatementProjectionInputV1(
        scope=scope,
        cutoff_at=cutoff,
        coverage_cutoff_at=cutoff,
        profile=profile,
        discovery_ref=prepared.request.annual,
        columns=tuple(columns),
        source_outcomes=tuple(outcomes),
        facts=tuple(evidence),
        missing_evidence=tuple(missing_evidence),
    )
    envelope = StatementReleaseEnvelopeV1(
        original_preparation=original_preparation,
        mapping_version=mapping_version,
        projection=projection,
        statements=project_annual_statements(
            projection, executable_digest=statement_executable_digest()
        ),
    )
    publication = artifacts.put_with_receipt(
        "annual-statement-release-input-" + sha256_digest(envelope),
        envelope,
        dependency_hashes=tuple(sorted({ref.content_hash for ref in refs})),
    )
    refs.append(
        _reference(artifacts, publication.artifact.artifact_id, STATEMENT_RELEASE_ROLE)
    )
    unique = {(ref.artifact_id, ref.role): ref for ref in refs}
    retained = tuple(unique[key] for key in sorted(unique))
    taxonomy = tuple(
        ref
        for ref in retained
        if ref.role in {"sec-taxonomy-manifest-v1", "sec-taxonomy-cache-archive-v1"}
    )
    if not taxonomy:
        raise DataReleaseError(
            "STATEMENT_RELEASE_TAXONOMY_UNAVAILABLE",
            "statement release requires its retained taxonomy inputs",
        )
    payload = dict(
        profile_id=statement_release_namespace(scope, cutoff, profile.digest),
        release_id="annual-statement-release-" + publication.artifact.content_hash,
        created_at=max(captured),
        snapshot_refs=tuple(sorted(snapshot_refs, key=lambda ref: ref.snapshot_id)),
        mapping_refs=tuple(
            MappingRefV1(mapping_id=key, mapping_digest=sha256_digest(mapping))
            for key, mapping in sorted(used_mappings.items())
        ),
        taxonomy_refs=taxonomy,
        parser_version=snapshot.parser_version,
        quality_profile_digest=profile.digest,
        required_fields=tuple(sorted(row.row_id for row in profile.rows)),
        artifact_refs=retained,
    )
    manifest = DataReleaseManifestV1.model_validate_json(
        canonical_bytes({**payload, "manifest_digest": sha256_digest(payload)})
    )
    return AutomaticDataReleaseRequestV1(
        manifest=manifest,
        content=DataReleaseContentRequestV1(
            source_revision=source_revision,
            evidence_refs=retained,
            mapping_reviews=tuple(reviews[key] for key in sorted(reviews)),
        ),
    )
