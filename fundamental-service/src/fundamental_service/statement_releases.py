from __future__ import annotations

from typing import Final, Literal, Protocol
from datetime import datetime

from pydantic import Field, model_validator

from .annual_statements import project_annual_statements
from .annual_discovery import AnnualFilingV1
from .artifact_evidence import (
    EvidenceArtifactReader,
    read_retained_artifact,
    retained_artifact_operation,
)
from .automatic_mapping_evidence import AutomaticMappingEvidenceChecks
from .contracts import (
    CanonicalFactV1,
    MissingValueV1,
    QualityStatus,
    SecIntegrityEvidenceV1,
    SourceSnapshotV1,
)
from .data_releases import (
    ArtifactRefV1,
    DataReleaseError,
    DataReleaseManifestV1,
    ReleaseModel,
)
from .facts import CanonicalMappingV1, canonical_fact_digest
from .issuer_classification import IssuerClassificationRequestV1
from .original_preparation import OriginalPreparation
from .original_issuer import IssuerOperatingSourceV1
from .registered_statement_rows import (
    primary_statement_scope_evidence,
    require_registered_primary_statement_scope,
    statement_cash_basis,
)
from .serialization import canonical_bytes, sha256_digest
from .snapshots import ContentAddressedStore
from .statement_contracts import (
    AnnualStatementsV1,
    DurationStatementPeriodV1,
    StatementAvailableSourceV1,
    StatementProjectionInputV1,
    StatementScopeV1,
    StatementMissingEvidenceV1,
    StatementUnavailableSourceV1,
    StatementAnnualColumnV1,
    UnresolvedStatementPeriodV1,
)
from .statement_issuer_scope import (
    reproduce_statement_issuer_classification,
    require_statement_issuer_scope,
)
from .statement_profiles import annual_statement_profile, statement_executable_digest
from .statement_mapping_evidence import (
    statement_missing_evidence,
    verify_statement_mapping_outcomes,
)

STATEMENT_RELEASE_ROLE: Final = "annual-statement-release-input-v1"


def unavailable_statement_original(
    filing: AnnualFilingV1, outcome_ref: ArtifactRefV1, issue_codes: tuple[str, ...]
) -> tuple[StatementUnavailableSourceV1, StatementAnnualColumnV1]:
    missing = MissingValueV1(status="unresolved", reason="; ".join(issue_codes))
    outcome = StatementUnavailableSourceV1(
        accession_number=filing.accession_number,
        available_at=filing.accepted_at,
        report_period_end=filing.report_period_end,
        outcome_ref=outcome_ref,
        quality_status=QualityStatus.ABSTAIN,
        missing=missing,
        issue_codes=issue_codes,
    )
    column = StatementAnnualColumnV1(
        fiscal_label=f"FY{filing.report_period_end.year}",
        period=UnresolvedStatementPeriodV1(
            reported_period_end=filing.report_period_end,
            missing=missing,
            source_outcome_ref=outcome_ref,
        ),
        original_accession=filing.accession_number,
    )
    return outcome, column


class StatementReleaseEnvelopeV1(ReleaseModel):
    protocol: Literal["annual-statement-release-input-v1"] = STATEMENT_RELEASE_ROLE
    original_preparation: ArtifactRefV1
    mapping_version: str = Field(min_length=1)
    projection: StatementProjectionInputV1
    statements: AnnualStatementsV1

    @model_validator(mode="after")
    def original_and_result_are_pinned(self) -> StatementReleaseEnvelopeV1:
        if (
            self.original_preparation.role != "sec-original-preparation-v1"
            or self.original_preparation.media_type != "application/json"
            or self.projection.profile
            != annual_statement_profile(executable_digest=statement_executable_digest())
            or project_annual_statements(
                self.projection, executable_digest=statement_executable_digest()
            )
            != self.statements
        ):
            raise ValueError("STATEMENT_RELEASE_RESULT_MISMATCH")
        return self


def statement_release_namespace(
    scope: StatementScopeV1, cutoff_at: datetime, profile_digest: str
) -> str:
    return "annual-statements:" + sha256_digest(
        {
            "scope": scope,
            "cutoff_at": cutoff_at,
            "profile_digest": profile_digest,
        }
    )


def read_statement_release(
    manifest: DataReleaseManifestV1, *, artifacts: EvidenceArtifactReader
) -> StatementReleaseEnvelopeV1 | None:
    refs = tuple(
        ref for ref in manifest.artifact_refs if ref.role == STATEMENT_RELEASE_ROLE
    )
    if not refs:
        return None
    if len(refs) != 1 or refs[0].media_type != "application/json":
        raise DataReleaseError(
            "STATEMENT_RELEASE_ENVELOPE_INVALID",
            "statement purpose requires one exact JSON envelope",
        )
    raw = read_retained_artifact(artifacts, refs[0])
    try:
        envelope = StatementReleaseEnvelopeV1.model_validate_json(raw)
    except ValueError as error:
        raise DataReleaseError(
            "STATEMENT_RELEASE_ENVELOPE_INVALID",
            "retained statement envelope is invalid",
        ) from error
    projection = envelope.projection
    if (
        raw != canonical_bytes(envelope)
        or type(manifest) is not DataReleaseManifestV1
        or manifest.profile_id
        != statement_release_namespace(
            projection.scope, projection.cutoff_at, projection.profile.digest
        )
        or manifest.quality_profile_digest != projection.profile.digest
        or manifest.required_fields
        != tuple(sorted(row.row_id for row in projection.profile.rows))
        or manifest.valuation_working_capital_policy is not None
        or manifest.conditional_capital_policies
        or manifest.conditional_reinvestment_policies
    ):
        raise DataReleaseError(
            "STATEMENT_RELEASE_CONTEXT_MISMATCH",
            "statement envelope differs from its exact release namespace and profile",
        )
    return envelope


class StatementSnapshotReader(Protocol):
    def get(self, snapshot_id: str) -> SourceSnapshotV1 | IssuerOperatingSourceV1: ...


class StatementFactReader(Protocol):
    def get(self, fact_id: str) -> CanonicalFactV1: ...


class StatementMappingReader(Protocol):
    def get_mapping(self, mapping_id: str) -> CanonicalMappingV1: ...


class StatementReleaseChecksV1(ReleaseModel):
    snapshot_ids: tuple[str, ...]
    fact_digests: tuple[str, ...]
    regulatory_evidence_digests: tuple[str, ...]


def verify_statement_release_membership(
    manifest: DataReleaseManifestV1,
    envelope: StatementReleaseEnvelopeV1,
    *,
    originals: OriginalPreparation,
    content: ContentAddressedStore,
    snapshots: StatementSnapshotReader,
    facts: StatementFactReader,
    mappings: StatementMappingReader,
    artifacts: EvidenceArtifactReader,
    source_revision: str,
) -> StatementReleaseChecksV1:
    artifact_ids = tuple(
        sorted(
            {
                reference.artifact_id
                for reference in (*manifest.artifact_refs, *manifest.taxonomy_refs)
            }
        )
    )
    with retained_artifact_operation(artifacts, artifact_ids) as artifacts:
        return _verify_statement_release_membership(
            manifest,
            envelope,
            originals=originals,
            content=content,
            snapshots=snapshots,
            facts=facts,
            mappings=mappings,
            artifacts=artifacts,
            source_revision=source_revision,
            mapping_checks=AutomaticMappingEvidenceChecks(),
        )


def _verify_statement_release_membership(
    manifest: DataReleaseManifestV1,
    envelope: StatementReleaseEnvelopeV1,
    *,
    originals: OriginalPreparation,
    content: ContentAddressedStore,
    snapshots: StatementSnapshotReader,
    facts: StatementFactReader,
    mappings: StatementMappingReader,
    artifacts: EvidenceArtifactReader,
    source_revision: str,
    mapping_checks: AutomaticMappingEvidenceChecks,
) -> StatementReleaseChecksV1:
    reference = envelope.original_preparation
    if originals.reference(reference.artifact_id, reference.role) != reference:
        raise DataReleaseError(
            "STATEMENT_RELEASE_PREPARATION_MISMATCH",
            "statement original preparation reference differs",
        )
    prepared, validations = originals.read_with_validations(
        reference.artifact_id, original_checks=mapping_checks.originals
    )
    projection = envelope.projection
    if projection.discovery_ref != prepared.request.annual:
        raise DataReleaseError(
            "STATEMENT_RELEASE_DISCOVERY_MISMATCH",
            "statement selection differs from its frozen discovery",
        )
    required_refs = {
        reference,
        projection.discovery_ref,
        *(outcome.outcome_ref for outcome in projection.source_outcomes),
    }
    if not required_refs <= set(manifest.artifact_refs):
        raise DataReleaseError(
            "STATEMENT_RELEASE_EVIDENCE_CLOSURE_MISSING",
            "statement release must retain its discovery, original preparation, and every source outcome",
        )
    by_accession = {v.request.filing.accession_number: v for v in validations}
    prepared_items = {
        v.request.filing.accession_number: item
        for item, v in zip(prepared.filings, validations, strict=True)
    }
    if set(by_accession) != {
        source.accession_number for source in projection.source_outcomes
    } or set(by_accession) != {
        column.original_accession for column in projection.columns
    }:
        raise DataReleaseError(
            "STATEMENT_RELEASE_ORIGINALS_MISMATCH",
            "statement coverage must retain every selected original",
        )
    snapshot_refs = {ref.snapshot_id: ref for ref in manifest.snapshot_refs}
    fact_evidence = {item.fact.fact_id: item for item in projection.facts}
    declared = {
        fact.fact_id: (ref.snapshot_id, fact.fact_digest)
        for ref in manifest.snapshot_refs
        for fact in ref.facts
    }
    if len(declared) != sum(len(ref.facts) for ref in manifest.snapshot_refs) or set(
        declared
    ) != set(fact_evidence):
        raise DataReleaseError(
            "STATEMENT_RELEASE_FACT_SET_MISMATCH",
            "statement facts must exactly match the released fact set",
        )
    used_snapshots: set[str] = set()
    used_mappings: dict[str, str] = {}
    regulatory: list[str] = []
    expected_missing: list[StatementMissingEvidenceV1] = []
    for outcome in projection.source_outcomes:
        validation = by_accession[outcome.accession_number]
        prepared_item = prepared_items[outcome.accession_number]
        request = validation.request
        if (
            request.cik != projection.scope.issuer_id
            or request.valuation_timestamp != projection.cutoff_at
            or request.filing.report_period_end != outcome.report_period_end
            or request.filing.accepted_at != outcome.available_at
        ):
            raise DataReleaseError(
                "STATEMENT_RELEASE_SOURCE_CONTEXT_MISMATCH",
                "statement original differs from issuer, period, or cutoff",
            )
        if (
            next(
                column.fiscal_label
                for column in projection.columns
                if column.original_accession == outcome.accession_number
            )
            != f"FY{request.filing.report_period_end.year}"
        ):
            raise DataReleaseError(
                "STATEMENT_RELEASE_PERIOD_MISMATCH",
                "statement fiscal label differs from its retained original report period",
            )
        if outcome.outcome_ref != originals.reference(
            validation.artifact_id, "sec-original-validation-v1"
        ):
            raise DataReleaseError(
                "STATEMENT_RELEASE_SOURCE_OUTCOME_MISMATCH",
                "statement source outcome differs from its retained original validation",
            )
        if not isinstance(outcome, StatementAvailableSourceV1):
            column = next(
                column
                for column in projection.columns
                if column.original_accession == outcome.accession_number
            )
            if not prepared_item.issue_codes or (
                outcome,
                column,
            ) != unavailable_statement_original(
                request.filing, outcome.outcome_ref, prepared_item.issue_codes
            ):
                raise DataReleaseError(
                    "STATEMENT_RELEASE_UNAVAILABLE_UNPROVEN",
                    "unavailable originals require their exact retained validation outcome",
                )
            continue
        if (
            validation.original is None
            or validation.integrity is None
            or prepared_item.issue_codes
            or prepared_item.identity is None
        ):
            raise DataReleaseError(
                "STATEMENT_RELEASE_VALIDATION_UNAVAILABLE",
                "available statement original requires passing strict validation",
            )
        require_registered_primary_statement_scope(validation.original)
        classification = reproduce_statement_issuer_classification(
            request=IssuerClassificationRequestV1(
                issuer_id=request.cik,
                accession_number=request.filing.accession_number,
                report_period_end=request.filing.report_period_end,
                valuation_at=request.valuation_timestamp,
            ),
            captured_sources=validation.captured_sources,
            content=content,
        )
        require_statement_issuer_scope(classification)
        identities = {
            fact_evidence[fact_id].snapshot_id for fact_id in outcome.fact_ids
        }
        if len(identities) != 1:
            raise DataReleaseError(
                "STATEMENT_RELEASE_SOURCE_SNAPSHOT_MISMATCH",
                "each available original requires its own declared snapshot",
            )
        snapshot_id = next(iter(identities))
        ref = snapshot_refs.get(snapshot_id)
        snapshot = snapshots.get(snapshot_id)
        if (
            ref is None
            or not isinstance(snapshot, SourceSnapshotV1)
            or (
                snapshot.manifest_digest != ref.manifest_digest
                or snapshot.valuation_timestamp != projection.cutoff_at
                or snapshot.identity.issuer_id != projection.scope.issuer_id
                or snapshot.identity.security_id != projection.scope.security_id
                or snapshot.identity.currency != projection.scope.currency
                or snapshot.identity != prepared_item.identity
                or not isinstance(
                    snapshot.sec_integrity_evidence, SecIntegrityEvidenceV1
                )
                or snapshot.sec_integrity_evidence != validation.integrity
                or snapshot.validation_profile_digest
                != request.runtime.validation_profile_digest
                or snapshot.parser_version != manifest.parser_version
            )
        ):
            raise DataReleaseError(
                "STATEMENT_RELEASE_SOURCE_SNAPSHOT_MISMATCH",
                "statement snapshot differs from its independently validated original",
            )
        used_snapshots.add(snapshot_id)
        regulatory.append(
            sha256_digest(
                {
                    "snapshot_id": snapshot_id,
                    "validation": validation.digest,
                    "classification": classification.output_digest,
                }
            )
        )
        scope = primary_statement_scope_evidence(validation.original, "revenue")
        assert scope is not None
        period = tuple(
            (start, end)
            for start, end in scope.annual_periods
            if end == request.filing.report_period_end
        )
        column = next(
            column
            for column in projection.columns
            if column.original_accession == outcome.accession_number
        )
        if len(period) != 1 or column.period != DurationStatementPeriodV1(
            period_start=period[0][0], period_end=period[0][1]
        ):
            raise DataReleaseError(
                "STATEMENT_RELEASE_PERIOD_MISMATCH",
                "statement annual period differs from the reviewed original primary row",
            )
        batch_refs = {
            ref
            for fact_id in outcome.fact_ids
            for ref in fact_evidence[fact_id].mapping_evidence_refs
            if ref.role == "statement-mapping-batch-decision-v1"
        }
        if len(batch_refs) != 1:
            raise DataReleaseError(
                "STATEMENT_MAPPING_OUTCOME_UNAVAILABLE",
                "each statement original requires its complete row mapping outcomes",
            )
        batch_ref = next(iter(batch_refs))
        batch = verify_statement_mapping_outcomes(
            batch_ref,
            original=validation.original,
            artifacts=artifacts,
            source_revision=source_revision,
            profile=projection.profile,
            mapping_version=envelope.mapping_version,
            evidence_checks=mapping_checks,
        )
        expected_missing.extend(
            statement_missing_evidence(
                batch,
                batch_ref,
                projection.scope,
                column,
                {
                    fact_evidence[fact_id].fact.normalized_field
                    for fact_id in outcome.fact_ids
                },
            )
        )
        for fact_id in outcome.fact_ids:
            evidence = fact_evidence[fact_id]
            live = facts.get(fact_id)
            mapping = mappings.get_mapping(evidence.mapping.decision_id)
            if (
                live != evidence.fact
                or canonical_fact_digest(live) != declared[fact_id][1]
                or declared[fact_id][0] != snapshot_id
                or mapping != evidence.mapping
                or mapping.mapping_version != envelope.mapping_version
                or evidence.snapshot_manifest_digest != snapshot.manifest_digest
                or evidence.source not in snapshot.source_records
                or evidence.source.content_hash
                != validation.original.source.content_hash
                or evidence.source.parser_input_hash
                != validation.original.source.parser_input_hash
                or evidence.fact.normalized_field not in manifest.required_fields
                or evidence.cash_basis
                != statement_cash_basis(
                    validation.original,
                    evidence.fact.normalized_field,
                    evidence.fact.concept,
                )
            ):
                raise DataReleaseError(
                    "STATEMENT_RELEASE_FACT_MISMATCH",
                    "statement value evidence differs from released canonical facts and source mapping",
                )
            used_mappings[mapping.decision_id] = sha256_digest(mapping)
    if used_snapshots != set(snapshot_refs) or used_mappings != {
        ref.mapping_id: ref.mapping_digest for ref in manifest.mapping_refs
    }:
        raise DataReleaseError(
            "STATEMENT_RELEASE_MEMBERSHIP_MISMATCH",
            "statement release contains undeclared or unused snapshots and mappings",
        )
    if tuple(sorted(projection.missing_evidence, key=sha256_digest)) != tuple(
        sorted(expected_missing, key=sha256_digest)
    ):
        raise DataReleaseError(
            "STATEMENT_MISSING_EVIDENCE_MISMATCH",
            "statement missing-row explanations must reproduce the original mapping outcomes",
        )
    for column in projection.columns:
        if isinstance(column.period, UnresolvedStatementPeriodV1) and isinstance(
            next(
                outcome
                for outcome in projection.source_outcomes
                if outcome.accession_number == column.original_accession
            ),
            StatementAvailableSourceV1,
        ):
            raise DataReleaseError(
                "STATEMENT_RELEASE_PERIOD_MISMATCH",
                "available originals require their actual annual duration",
            )
    return StatementReleaseChecksV1(
        snapshot_ids=tuple(sorted(used_snapshots)),
        fact_digests=tuple(
            sorted(canonical_fact_digest(item.fact) for item in projection.facts)
        ),
        regulatory_evidence_digests=tuple(sorted(regulatory)),
    )
