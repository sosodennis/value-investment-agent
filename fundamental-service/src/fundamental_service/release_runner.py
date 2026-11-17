"""Read-only validation and canary execution for immutable data releases.

The runner is deliberately independent from the serving application. It reads
immutable repositories, validates the candidate's signed evidence, and runs a
point-in-time fact selection without reading or changing the active pointer.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .artifact_evidence import read_retained_artifact, require_retained_artifact
from .parser_action_evidence import require_current_parser_action_refs
from .contracts import (
    CanonicalFactV1,
    SecIntegrityEvidenceV1,
    SecHistoryIntegrityEvidenceV1,
    SourceSnapshotV1,
    SourceRecordV1,
)
from .conditional_capital_contracts import CAPITAL_SUPPORTING_AWARD_FIELDS
from .automatic_mapping import verify_automatic_mapping_replay
from .automatic_mapping_evidence import AutomaticMappingEvidenceChecks
from .automatic_market_policy_evidence import (
    AUTOMATIC_MARKET_POLICY_ROLE,
    load_release_automatic_market_policy,
    requires_automatic_market_policy,
)
from .data_releases import (
    DataReleaseCandidatePublishRequestV1,
    DataReleaseContentRequestV1,
    DataReleaseError,
    AutomaticMappingApprovalV1,
    DataReleaseManifestV1,
    DataReleaseTrustRootsV1,
    DataReleaseVerificationV1,
    FactRefV1,
    MappingRefV1,
    IssuerOperatingReleaseManifestV1,
    verify_data_release_candidate,
    verify_release_mapping_approvals,
)
from .facts import (
    CanonicalFactRepository,
    CanonicalMappingV1,
    FilesystemCanonicalFactRepository,
    canonical_fact_digest,
    resolve_canonical_facts,
    verify_accounting_role_evidence,
    select_fact_groups,
)
from .equity_award_evidence import (
    EQUITY_DILUTION_ARTIFACT_ROLE,
    load_release_dilution_evidence,
    load_release_conditional_quote,
)
from .equity_dilution import (
    AWARD_FACT_FIELDS,
    DilutionError,
    compute_treasury_stock_dilution,
)
from .quote_providers import QuoteSourceProviderPort
from .macro_series import MacroSeriesProviderPort
from .market_reference import MarketReferenceProviderPort
from .industry_capital import requires_industry_capital_plan
from .market_reference_evidence import (
    read_release_market_reference_plan,
    load_release_market_reference_selection,
)
from .market_source_selection import MarketSourceError, verify_observed_market_inputs
from .terminal_growth_evidence import (
    read_release_terminal_growth_plan,
    load_release_terminal_growth_selection,
    requires_terminal_growth_plan,
)
from .policies import (
    PolicyRegistry,
    PolicyError,
    FilesystemPolicyRepository,
    initial_model_specs,
)
from .source_admission import SourceUsePolicyV1
from .source_admission_evidence import load_release_source_admissions
from .replay import ArtifactRecordV1, ArtifactStore
from .history_composition import verify_history_components
from .serialization import canonical_bytes, sha256_digest
from .snapshots import FilesystemSnapshotRepository, SnapshotError
from .sec_rebuild import parsed_facts_to_candidates
from .taxonomy_evidence import require_original_taxonomy
from .original_issuer import IssuerOperatingSourceV1, OriginalOperatingSourceV1
from .issuer_release_evidence import (
    require_issuer_release_profile,
    require_original_fact_membership,
    verify_original_bytes,
    verify_original_integrity,
)
from .working_capital import assess_composite_working_capital
from .valuation_release_inputs import (
    valuation_release_conditional_capital,
    valuation_release_requirements,
    valuation_release_working_capital_inputs,
)
from .conditional_reinvestment_release import valuation_release_conditional_reinvestment
from .valuation_preparation import (
    PreparationError,
    compose_conditional_operating_forecasts,
)
from .conditional_reinvestment import ConditionalReinvestmentError


class ReleaseMappingReader(Protocol):
    def get_mapping(self, mapping_id: str) -> CanonicalMappingV1: ...


class ReleaseArtifactReader(Protocol):
    def get(self, artifact_id: str) -> ArtifactRecordV1: ...

    def read(self, artifact_id: str) -> bytes: ...


class ReleaseSnapshotReader(Protocol):
    def get(self, snapshot_id: str) -> SourceSnapshotV1 | IssuerOperatingSourceV1: ...


class _SecuritySnapshots:
    def __init__(self, reader: ReleaseSnapshotReader) -> None:
        self.reader = reader

    def get(self, snapshot_id: str) -> SourceSnapshotV1:
        snapshot = self.reader.get(snapshot_id)
        if not isinstance(snapshot, SourceSnapshotV1):
            raise DataReleaseError(
                "DATA_RELEASE_SOURCE_SCOPE_MISMATCH",
                "security histories require security snapshots",
            )
        return snapshot


class DataReleaseCanaryReportV1(BaseModel):
    """Replayable evidence produced by a read-only candidate canary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verification: DataReleaseVerificationV1
    candidate_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    checked_snapshot_ids: tuple[str, ...] = ()
    checked_fact_digests: tuple[str, ...] = ()
    checked_artifact_digests: tuple[str, ...] = ()
    market_policy_checks: tuple[str, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    checked_operating_forecast_digests: tuple[str, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    canary_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canary_digest_matches(self) -> DataReleaseCanaryReportV1:
        payload = {
            "manifest_digest": self.candidate_manifest_digest,
            "verification_digest": self.verification.verification_digest,
            "source_revision": self.verification.source_revision,
            "snapshots": self.checked_snapshot_ids,
            "facts": self.checked_fact_digests,
            "artifacts": self.checked_artifact_digests,
        }
        if self.market_policy_checks:
            if self.market_policy_checks != tuple(
                sorted(set(self.market_policy_checks))
            ):
                raise ValueError("market policy checks are not canonical")
            payload["market_policy_checks"] = self.market_policy_checks
        if self.checked_operating_forecast_digests:
            if self.checked_operating_forecast_digests != tuple(
                sorted(set(self.checked_operating_forecast_digests))
            ):
                raise ValueError("operating forecast checks are not canonical")
            payload["operating_forecasts"] = self.checked_operating_forecast_digests
        if sha256_digest(payload) != self.canary_digest:
            raise ValueError("canary_digest does not match report evidence")
        return self


class DataReleaseContentReportV1(BaseModel):
    """Reproducible content checks; not a signed release verification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["data-release-content-report-v1"] = (
        "data-release-content-report-v1"
    )
    candidate_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    checked_snapshot_ids: tuple[str, ...]
    checked_fact_digests: tuple[str, ...]
    checked_artifact_digests: tuple[str, ...]
    market_policy_checks: tuple[str, ...] = ()
    checked_operating_forecast_digests: tuple[str, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class DataReleaseCanaryRunner:
    """Validate one candidate without resolving or mutating active release state."""

    def __init__(
        self,
        *,
        snapshot_repository: ReleaseSnapshotReader,
        fact_repository: CanonicalFactRepository,
        mapping_reader: ReleaseMappingReader,
        artifact_reader: ReleaseArtifactReader,
        trust_roots: DataReleaseTrustRootsV1,
        quote_providers: tuple[QuoteSourceProviderPort, ...] = (),
        macro_providers: tuple[MacroSeriesProviderPort, ...] = (),
        reference_providers: tuple[MarketReferenceProviderPort, ...] = (),
        source_use_policy: SourceUsePolicyV1 | None = None,
        policy_registry: PolicyRegistry | None = None,
    ) -> None:
        self._snapshots = snapshot_repository
        self._facts = fact_repository
        self._mappings = mapping_reader
        self._artifacts = artifact_reader
        self._trust_roots = trust_roots
        self._quote_providers = quote_providers
        self._macro_providers = macro_providers
        self._reference_providers = reference_providers
        self._source_use_policy = source_use_policy
        self._policy_registry = policy_registry

    def validate(
        self,
        manifest: DataReleaseManifestV1,
        verification: DataReleaseVerificationV1,
    ) -> DataReleaseCanaryReportV1:
        verify_data_release_candidate(manifest, verification, self._trust_roots)
        content = self.validate_content(
            manifest,
            DataReleaseContentRequestV1(
                source_revision=verification.source_revision,
                evidence_refs=verification.evidence_refs,
                mapping_reviews=verification.mapping_reviews,
            ),
        )
        canary_payload = {
            "manifest_digest": manifest.manifest_digest,
            "verification_digest": verification.verification_digest,
            "source_revision": verification.source_revision,
            "snapshots": content.checked_snapshot_ids,
            "facts": content.checked_fact_digests,
            "artifacts": content.checked_artifact_digests,
        }
        if content.market_policy_checks:
            canary_payload["market_policy_checks"] = content.market_policy_checks
        if content.checked_operating_forecast_digests:
            canary_payload["operating_forecasts"] = (
                content.checked_operating_forecast_digests
            )
        return DataReleaseCanaryReportV1(
            verification=verification,
            candidate_manifest_digest=manifest.manifest_digest,
            checked_snapshot_ids=content.checked_snapshot_ids,
            checked_fact_digests=content.checked_fact_digests,
            checked_artifact_digests=content.checked_artifact_digests,
            market_policy_checks=content.market_policy_checks,
            checked_operating_forecast_digests=content.checked_operating_forecast_digests,
            canary_digest=sha256_digest(canary_payload),
        )

    def validate_content(
        self,
        manifest: DataReleaseManifestV1,
        request: DataReleaseContentRequestV1,
    ) -> DataReleaseContentReportV1:
        """Run owning validators before a trusted workflow signs their result."""
        # Preserve issuer-operating subtype validation at this internal boundary.
        manifest = type(manifest).model_validate_json(canonical_bytes(manifest))
        request = DataReleaseContentRequestV1.model_validate_json(
            canonical_bytes(request)
        )
        verify_release_mapping_approvals(
            manifest, request.mapping_reviews, self._trust_roots
        )
        if isinstance(manifest, IssuerOperatingReleaseManifestV1):
            require_issuer_release_profile(manifest)
        if manifest.valuation_working_capital_policy is not None:
            valuation_release_requirements(
                manifest, manifest.valuation_working_capital_policy.model_id
            )
        if manifest.conditional_capital_policies:
            valuation_release_requirements(
                manifest, manifest.conditional_capital_policies[0].model_id
            )
        if manifest.conditional_reinvestment_policies:
            valuation_release_requirements(
                manifest, manifest.conditional_reinvestment_policies[0].recipe.model_id
            )
        self._verify_artifacts(manifest, request)
        admissions = load_release_source_admissions(
            manifest,
            artifacts=self._artifacts,
            policy=self._source_use_policy,
            macro_providers=self._macro_providers,
            reference_providers=self._reference_providers,
        )
        market_policy_checks = []
        plan = read_release_market_reference_plan(manifest, artifacts=self._artifacts)
        terminal_plan = read_release_terminal_growth_plan(
            manifest, artifacts=self._artifacts
        )
        automatic_policy_declared = any(
            ref.role == AUTOMATIC_MARKET_POLICY_ROLE for ref in manifest.artifact_refs
        )
        if (
            terminal_plan is None or plan is None
        ) and self._policy_registry is not None:
            for candidate in self._policy_registry.policies():
                if not (
                    terminal_plan is None
                    and requires_terminal_growth_plan(candidate)
                    or plan is None
                    and requires_industry_capital_plan(candidate.market_inputs)
                    or requires_automatic_market_policy(candidate)
                ):
                    continue
                for ref in manifest.snapshot_refs:
                    snapshot = self._snapshots.get(ref.snapshot_id)
                    if not isinstance(snapshot, SourceSnapshotV1):
                        continue
                    if candidate.issuer_id not in {
                        None,
                        snapshot.identity.issuer_id,
                    }:
                        continue
                    try:
                        effective = self._policy_registry.select_policy(
                            model_id=candidate.model_id,
                            model_version=candidate.model_version,
                            valuation_timestamp=snapshot.valuation_timestamp,
                            policy_id=None,
                            issuer_id=snapshot.identity.issuer_id,
                            data_release_manifest_digest=manifest.manifest_digest,
                        )
                    except PolicyError as error:
                        if error.code == "POLICY_NOT_FOUND":
                            continue
                        raise DataReleaseError(error.code, str(error)) from error
                    load_release_automatic_market_policy(
                        manifest,
                        snapshot=snapshot,
                        policy=effective,
                        admissions=admissions,
                        artifacts=self._artifacts,
                        expected_source_revision=request.source_revision,
                    )
                    load_release_terminal_growth_selection(
                        manifest,
                        snapshot=snapshot,
                        policy=effective,
                        admissions=admissions,
                        artifacts=self._artifacts,
                    )
                    load_release_market_reference_selection(
                        manifest,
                        snapshot=snapshot,
                        policy=effective,
                        admissions=admissions,
                        artifacts=self._artifacts,
                    )
        declared_plan = plan or terminal_plan
        if declared_plan is not None or automatic_policy_declared:
            if declared_plan is None:
                raise DataReleaseError(
                    "AUTOMATIC_MARKET_POLICY_CONTEXT_MISMATCH",
                    "automatic market-policy evidence requires its selection plans",
                )
            if self._policy_registry is None:
                raise DataReleaseError(
                    "MARKET_REFERENCE_POLICY_UNAVAILABLE",
                    "reference canary requires configured deployment policy authority",
                )
            declared_policy = self._policy_registry.policy(declared_plan.policy_id)
            if declared_policy is None or declared_policy.market_inputs is None:
                raise DataReleaseError(
                    "MARKET_REFERENCE_POLICY_UNAVAILABLE",
                    "reference canary requires a complete deployment market policy",
                )
            for ref in manifest.snapshot_refs:
                snapshot = self._snapshots.get(ref.snapshot_id)
                if not isinstance(snapshot, SourceSnapshotV1):
                    raise DataReleaseError(
                        "MARKET_REFERENCE_SNAPSHOT_SCOPE_UNSUPPORTED",
                        "market reference plan requires a security valuation snapshot",
                    )
                try:
                    policy = self._policy_registry.select_policy(
                        model_id=declared_policy.model_id,
                        model_version=declared_policy.model_version,
                        valuation_timestamp=snapshot.valuation_timestamp,
                        policy_id=None,
                        issuer_id=snapshot.identity.issuer_id,
                        data_release_manifest_digest=manifest.manifest_digest,
                    )
                    automatic_policy = load_release_automatic_market_policy(
                        manifest,
                        snapshot=snapshot,
                        policy=policy,
                        admissions=admissions,
                        artifacts=self._artifacts,
                        expected_source_revision=request.source_revision,
                    )
                    selection = load_release_market_reference_selection(
                        manifest,
                        snapshot=snapshot,
                        policy=policy,
                        admissions=admissions,
                        artifacts=self._artifacts,
                    )
                    terminal_selection = load_release_terminal_growth_selection(
                        manifest,
                        snapshot=snapshot,
                        policy=policy,
                        admissions=admissions,
                        artifacts=self._artifacts,
                    )
                    if policy.market_inputs is None:
                        raise DataReleaseError(
                            "MARKET_REFERENCE_POLICY_UNAVAILABLE",
                            "effective reference policy has no complete market inputs",
                        )
                    verify_observed_market_inputs(
                        policy.market_inputs,
                        admissions=admissions,
                        valuation_at=snapshot.valuation_timestamp,
                        currency=snapshot.identity.currency,
                        reference_selection=selection,
                    )
                    selection_pins = {}
                    if automatic_policy is not None:
                        selection_pins["automatic_market_policy"] = (
                            automatic_policy.decision.output_digest
                        )
                    if selection is not None:
                        selection_pins["reference_selection"] = selection.output_digest
                    if terminal_selection is not None:
                        selection_pins["terminal_selection"] = (
                            terminal_selection.output_digest
                        )
                    market_policy_checks.append(
                        sha256_digest(
                            {
                                "snapshot_id": snapshot.snapshot_id,
                                "policy_digest": policy.policy_digest,
                                **selection_pins,
                            }
                        )
                    )
                except (PolicyError, MarketSourceError) as error:
                    raise DataReleaseError(error.code, str(error)) from error
        mappings = self._verify_mappings(manifest.mapping_refs)
        evidence_checks = AutomaticMappingEvidenceChecks()
        self._verify_automatic_mappings(
            manifest, request, mappings, evidence_checks=evidence_checks
        )
        checked_snapshots, checked_facts, checked_forecasts = (
            self._verify_snapshots_and_facts(manifest, mappings)
        )
        self._verify_equity_dilution(manifest)
        require_current_parser_action_refs(
            (
                *manifest.artifact_refs,
                *request.evidence_refs,
                *(
                    ref
                    for review in request.mapping_reviews
                    for ref in review.evidence_refs
                ),
            ),
            artifacts=self._artifacts,
            build_checks=evidence_checks.builds,
        )

        return DataReleaseContentReportV1(
            candidate_manifest_digest=manifest.manifest_digest,
            request_digest=sha256_digest(request),
            checked_snapshot_ids=checked_snapshots,
            checked_fact_digests=checked_facts,
            checked_artifact_digests=self._artifact_digests(manifest, request),
            market_policy_checks=tuple(sorted(set(market_policy_checks))),
            checked_operating_forecast_digests=checked_forecasts,
        )

    def _verify_automatic_mappings(
        self,
        manifest: DataReleaseManifestV1,
        verification: DataReleaseContentRequestV1,
        mappings: dict[str, CanonicalMappingV1],
        *,
        evidence_checks: AutomaticMappingEvidenceChecks,
    ) -> None:
        indexed = (
            self._mapping_fact_references(manifest)
            if any(
                isinstance(review, AutomaticMappingApprovalV1)
                for review in verification.mapping_reviews
            )
            else None
        )
        for review in verification.mapping_reviews:
            mapping = mappings[review.mapping_id]
            if not isinstance(review, AutomaticMappingApprovalV1):
                if mapping.observation_scope is not None:
                    raise DataReleaseError(
                        "DATA_RELEASE_MAPPING_METHOD_MISMATCH",
                        "machine scoped mappings require automatic approval evidence",
                    )
                continue
            request = verify_automatic_mapping_replay(
                review,
                mapping,
                artifacts=self._artifacts,
                evidence_checks=evidence_checks,
            )
            used = False
            for index, ref in enumerate(manifest.snapshot_refs):
                references = (
                    indexed[index].get(mapping.decision_id, ())
                    if indexed is not None
                    else ref.facts
                )
                declared = tuple(
                    fact
                    for item in references
                    if (fact := self._read_declared_fact(item)).mapping_decision_id
                    == mapping.decision_id
                )
                if not declared:
                    continue
                used = True
                snapshot = self._snapshots.get(ref.snapshot_id)
                sources: tuple[OriginalOperatingSourceV1 | SourceRecordV1, ...]
                if isinstance(snapshot, IssuerOperatingSourceV1):
                    sources = tuple(
                        item.source
                        for item in snapshot.originals
                        if item.source == request.original.source
                        and item.report.replay_digest()
                        == request.original.report.replay_digest()
                    )
                    security_id = None
                else:
                    evidence = snapshot.sec_integrity_evidence
                    integrities = (
                        tuple(item.integrity for item in evidence.components)
                        if isinstance(evidence, SecHistoryIntegrityEvidenceV1)
                        else (evidence,)
                    )
                    sources = tuple(
                        source
                        for source in snapshot.source_records
                        if source.accession_number
                        == request.original.source.accession_number
                        and source.uri == request.original.source.uri
                        and source.content_hash == request.original.source.content_hash
                        and source.parser_input_hash
                        == request.original.source.parser_input_hash
                        and source.available_at == request.original.source.available_at
                        and not source.is_amendment
                        and source.form == "10-K"
                        and request.integrity in integrities
                    )
                    security_id = snapshot.identity.security_id
                if (
                    len(sources) != 1
                    or snapshot.identity.issuer_id != request.original.source.cik
                    or request.original.decision_at > snapshot.valuation_timestamp
                ):
                    raise DataReleaseError(
                        "DATA_RELEASE_MAPPING_SOURCE_MISMATCH",
                        "automatic mapping cannot authorize another original or cutoff",
                    )
                candidates = parsed_facts_to_candidates(
                    request.original.report,
                    source=sources[0],
                    issuer_id=snapshot.identity.issuer_id,
                    security_id=security_id,
                    normalized_field=mapping.normalized_field,
                    mapping=mapping,
                    input_digests=evidence_checks.identities,
                )
                expected = {
                    canonical_fact_digest(selection.fact)
                    for selection in select_fact_groups(
                        candidates, snapshot.valuation_timestamp
                    )
                    if selection.fact is not None
                }
                if any(
                    canonical_fact_digest(fact) not in expected for fact in declared
                ):
                    raise DataReleaseError(
                        "DATA_RELEASE_MAPPING_OBSERVATION_MISMATCH",
                        "released facts must reproduce the approved observations",
                    )
            if not used:
                raise DataReleaseError(
                    "DATA_RELEASE_MAPPING_UNUSED",
                    "automatic mapping has no released facts",
                )

    def _read_declared_fact(self, reference: FactRefV1) -> CanonicalFactV1:
        fact = self._facts.get(reference.fact_id)
        if canonical_fact_digest(fact) != reference.fact_digest:
            raise DataReleaseError(
                "DATA_RELEASE_FACT_MISMATCH",
                f"release fact {reference.fact_id} has a different digest",
            )
        return fact

    def _mapping_fact_references(
        self,
        manifest: DataReleaseManifestV1,
        *,
        max_entries: int = 8192,
        max_retained_bytes: int = 2 * 1024 * 1024,
    ) -> tuple[dict[str, list[FactRefV1]], ...] | None:
        if sum(len(ref.facts) for ref in manifest.snapshot_refs) > max_entries:
            return None
        indexed: list[dict[str, list[FactRefV1]]] = []
        retained = sys.getsizeof(indexed)
        for ref in manifest.snapshot_refs:
            groups: dict[str, list[FactRefV1]] = {}
            previous = sys.getsizeof(indexed)
            indexed.append(groups)
            retained += sys.getsizeof(groups) + sys.getsizeof(indexed) - previous
            for item in ref.facts:
                fact = self._read_declared_fact(item)
                decision = fact.mapping_decision_id or ""
                if decision not in groups:
                    previous = sys.getsizeof(groups)
                    groups[decision] = []
                    retained += (
                        sys.getsizeof(groups)
                        - previous
                        + sys.getsizeof(decision)
                        + sys.getsizeof(groups[decision])
                    )
                values = groups[decision]
                previous = sys.getsizeof(values)
                values.append(item)
                retained += sys.getsizeof(values) - previous + sys.getsizeof(item)
                if retained > max_retained_bytes:
                    return None
        return tuple(indexed)

    def _verify_equity_dilution(self, manifest: DataReleaseManifestV1) -> None:
        references = tuple(
            ref
            for ref in manifest.artifact_refs
            if ref.role == EQUITY_DILUTION_ARTIFACT_ROLE
        )
        if manifest.conditional_capital_policies:
            try:
                for declaration in manifest.snapshot_refs:
                    snapshot = self._snapshots.get(declaration.snapshot_id)
                    if not isinstance(snapshot, SourceSnapshotV1):
                        raise DataReleaseError(
                            "DATA_RELEASE_SOURCE_SCOPE_MISMATCH",
                            "conditional quotes require a security snapshot",
                        )
                    policy = next(
                        item
                        for item in manifest.conditional_capital_policies
                        if item.snapshot_manifest_digest == snapshot.manifest_digest
                    )
                    load_release_conditional_quote(
                        manifest,
                        policy=policy,
                        snapshot=snapshot,
                        artifacts=self._artifacts,
                        quote_providers=self._quote_providers,
                        source_use_policy=self._source_use_policy,
                    )
            except (DilutionError, SnapshotError, ValueError) as error:
                raise DataReleaseError(
                    getattr(error, "code", "DILUTION_EVIDENCE_INVALID"), str(error)
                ) from error
            return
        has_award_facts = any(
            self._facts.get(ref.fact_id).normalized_field
            in CAPITAL_SUPPORTING_AWARD_FIELDS
            for snapshot in manifest.snapshot_refs
            for ref in snapshot.facts
        )
        if not references and not has_award_facts:
            return
        matched = 0
        try:
            for declaration in manifest.snapshot_refs:
                snapshot = self._snapshots.get(declaration.snapshot_id)
                if isinstance(snapshot, IssuerOperatingSourceV1):
                    raise DataReleaseError(
                        "DATA_RELEASE_SOURCE_SCOPE_MISMATCH",
                        "issuer operating releases cannot authorize equity dilution",
                    )
                facts = tuple(self._facts.get(ref.fact_id) for ref in declaration.facts)
                evidence = load_release_dilution_evidence(
                    manifest,
                    snapshot=snapshot,
                    artifacts=self._artifacts,
                    released_facts=facts,
                    quote_providers=self._quote_providers,
                    source_use_policy=self._source_use_policy,
                )
                declared_awards = {
                    fact.fact_id
                    for fact in facts
                    if fact.normalized_field in CAPITAL_SUPPORTING_AWARD_FIELDS
                }
                if evidence is None:
                    if declared_awards:
                        raise DilutionError(
                            "DILUTION_EVIDENCE_MISSING",
                            "release award observations lack their reviewed inventory",
                        )
                    continue
                matched += 1
                compute_treasury_stock_dilution(
                    evidence.inventory,
                    evidence.quote,
                    evidence.policy,
                    valuation_timestamp=snapshot.valuation_timestamp,
                )
            if matched != len(references):
                raise DilutionError(
                    "DILUTION_SNAPSHOT_MISMATCH",
                    "award evidence must bind one declared snapshot",
                )
        except (DilutionError, SnapshotError, ValueError) as error:
            raise DataReleaseError(
                getattr(error, "code", "DILUTION_EVIDENCE_INVALID"), str(error)
            ) from error

    def _verify_artifacts(
        self,
        manifest: DataReleaseManifestV1,
        verification: DataReleaseContentRequestV1,
    ) -> None:
        refs = (
            *manifest.taxonomy_refs,
            *manifest.artifact_refs,
            *verification.evidence_refs,
        )
        refs += tuple(
            evidence_ref
            for review in verification.mapping_reviews
            for evidence_ref in review.evidence_refs
        )
        expected: dict[str, str] = {}
        checked: dict[str, ArtifactRecordV1] = {}
        for reference in refs:
            previous = expected.setdefault(
                reference.artifact_id, reference.content_hash
            )
            if previous != reference.content_hash:
                raise DataReleaseError(
                    "DATA_RELEASE_ARTIFACT_REFERENCE_CONFLICT",
                    "candidate references one artifact ID with different hashes",
                )
            try:
                record = require_retained_artifact(self._artifacts, reference)
                previous_record = checked.get(reference.artifact_id)
                if previous_record is not None:
                    if record != previous_record:
                        raise DataReleaseError(
                            "ARTIFACT_EVIDENCE_CHANGED",
                            "release artifact metadata changed during verification",
                        )
                    continue
                content = read_retained_artifact(self._artifacts, reference)
                actual = hashlib.sha256(content).hexdigest()
                if actual != reference.content_hash:
                    raise DataReleaseError(
                        "DATA_RELEASE_ARTIFACT_HASH_MISMATCH",
                        f"release artifact {reference.artifact_id} failed hash verification",
                    )
                if self._artifacts.get(reference.artifact_id) != record:
                    raise DataReleaseError(
                        "ARTIFACT_EVIDENCE_CHANGED",
                        "release artifact metadata changed during verification",
                    )
            except DataReleaseError:
                raise
            except Exception as exc:  # pragma: no cover - adapter boundary
                raise DataReleaseError(
                    "DATA_RELEASE_ARTIFACT_UNAVAILABLE",
                    f"release artifact {reference.artifact_id} is unavailable",
                ) from exc
            checked[reference.artifact_id] = record

    def _artifact_digests(
        self,
        manifest: DataReleaseManifestV1,
        verification: DataReleaseContentRequestV1,
    ) -> tuple[str, ...]:
        refs = (
            *manifest.taxonomy_refs,
            *manifest.artifact_refs,
            *verification.evidence_refs,
        )
        refs += tuple(
            evidence_ref
            for review in verification.mapping_reviews
            for evidence_ref in review.evidence_refs
        )
        return tuple(sorted({reference.content_hash for reference in refs}))

    def _verify_snapshots_and_facts(
        self, manifest: DataReleaseManifestV1, mappings: dict[str, CanonicalMappingV1]
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        snapshot_ids: list[str] = []
        fact_digests: list[str] = []
        forecast_digests: list[str] = []
        declared_fields = set(manifest.required_fields)
        checked_composite_inputs: set[str] = set()
        valuation_input_policy = manifest.valuation_working_capital_policy
        all_composite_inputs = (
            manifest.working_capital_inputs
            if isinstance(manifest, IssuerOperatingReleaseManifestV1)
            else valuation_input_policy.inputs
            if valuation_input_policy is not None
            else ()
        )
        if valuation_input_policy is not None and any(
            mapping.mapping_version != valuation_input_policy.mapping_version
            for mapping in mappings.values()
        ):
            raise DataReleaseError(
                "DATA_RELEASE_MAPPING_VERSION_MISMATCH",
                "valuation input policy requires the pinned release mapping version",
            )
        for reference in manifest.snapshot_refs:
            try:
                snapshot = self._snapshots.get(reference.snapshot_id)
            except Exception as exc:  # pragma: no cover - adapter boundary
                raise DataReleaseError(
                    "DATA_RELEASE_SNAPSHOT_UNAVAILABLE",
                    f"release snapshot {reference.snapshot_id} is unavailable",
                ) from exc
            if snapshot.manifest_digest != reference.manifest_digest:
                raise DataReleaseError(
                    "DATA_RELEASE_SNAPSHOT_MISMATCH",
                    f"release snapshot {reference.snapshot_id} has a different manifest digest",
                )
            issuer_scope = isinstance(snapshot, IssuerOperatingSourceV1)
            if issuer_scope != isinstance(manifest, IssuerOperatingReleaseManifestV1):
                raise DataReleaseError(
                    "DATA_RELEASE_SOURCE_SCOPE_MISMATCH",
                    "issuer source views require their explicit operating release manifest",
                )
            try:
                if isinstance(snapshot, IssuerOperatingSourceV1):
                    assert isinstance(manifest, IssuerOperatingReleaseManifestV1)
                    self._verify_issuer_originals(snapshot, manifest)
                else:
                    verify_history_components(
                        snapshot, _SecuritySnapshots(self._snapshots)
                    )
            except DataReleaseError:
                raise
            except Exception as exc:
                raise DataReleaseError(
                    "DATA_RELEASE_HISTORY_COMPONENT_INVALID",
                    "release history does not match its independently validated originals",
                ) from exc
            base_fields = tuple(
                field
                for field in manifest.required_fields
                if field not in AWARD_FACT_FIELDS
            )
            resolved = (
                self._resolve_facts(snapshot, base_fields, mappings)
                if base_fields
                else ()
            )
            declared = {item.fact_id: item.fact_digest for item in reference.facts}
            actual = {item.fact_id: canonical_fact_digest(item) for item in resolved}
            if any(
                declared.get(fact_id) != digest for fact_id, digest in actual.items()
            ):
                raise DataReleaseError(
                    "DATA_RELEASE_FACT_MISMATCH",
                    f"release snapshot {reference.snapshot_id} failed its fact canary",
                )
            if {item.normalized_field for item in resolved} != set(base_fields):
                raise DataReleaseError(
                    "DATA_RELEASE_FIELDS_UNAVAILABLE",
                    f"release snapshot {reference.snapshot_id} does not cover required fields",
                )
            history = self._verify_declared_history(snapshot, reference.facts, mappings)
            if manifest.conditional_reinvestment_policies:
                if not isinstance(snapshot, SourceSnapshotV1):
                    raise DataReleaseError(
                        "DATA_RELEASE_SOURCE_SCOPE_MISMATCH",
                        "forward valuation inputs require a security snapshot",
                    )
                versions = {mapping.mapping_version for mapping in mappings.values()}
                if len(versions) != 1:
                    raise DataReleaseError(
                        "DATA_RELEASE_MAPPING_VERSION_MISMATCH",
                        "forward inputs require one coherent release mapping",
                    )
                reinvestment = valuation_release_conditional_reinvestment(
                    manifest,
                    snapshot,
                    history,
                    mapping_version=next(iter(versions)),
                    artifacts=self._artifacts,
                )
                assert reinvestment is not None
                try:
                    forecast = compose_conditional_operating_forecasts(
                        reinvestment.policy,
                        history,
                        snapshot=snapshot,
                        mapping_version=next(iter(versions)),
                    )
                except (PreparationError, ConditionalReinvestmentError) as error:
                    raise DataReleaseError(error.code, str(error)) from error
                forecast_digests.append(forecast.output_digest)
            if manifest.conditional_capital_policies:
                if not isinstance(snapshot, SourceSnapshotV1):
                    raise DataReleaseError(
                        "DATA_RELEASE_SOURCE_SCOPE_MISMATCH",
                        "conditional capital requires a security snapshot",
                    )
                versions = {mapping.mapping_version for mapping in mappings.values()}
                if len(versions) != 1:
                    raise DataReleaseError(
                        "DATA_RELEASE_MAPPING_VERSION_MISMATCH",
                        "conditional capital requires one coherent release mapping",
                    )
                valuation_release_conditional_capital(
                    manifest, snapshot, history, mapping_version=next(iter(versions))
                )
            if isinstance(snapshot, IssuerOperatingSourceV1):
                assert isinstance(manifest, IssuerOperatingReleaseManifestV1)
                if any(
                    mapping.mapping_version != manifest.mapping_version
                    for mapping in mappings.values()
                ):
                    raise DataReleaseError(
                        "DATA_RELEASE_MAPPING_VERSION_MISMATCH",
                        "issuer mappings require the pinned release version",
                    )
                require_original_fact_membership(snapshot, history, mappings)
            snapshot_composite_inputs = (
                tuple(
                    item
                    for item in all_composite_inputs
                    if item.issuer_id == snapshot.identity.issuer_id
                    and item.current_assets_fact_id in declared
                )
                if isinstance(snapshot, IssuerOperatingSourceV1)
                else valuation_release_working_capital_inputs(manifest, snapshot)
            )
            for policy_input in snapshot_composite_inputs:
                assessment = assess_composite_working_capital(
                    policy_input, history, snapshot=snapshot
                )
                if assessment.status != "estimated":
                    raise DataReleaseError(
                        "DATA_RELEASE_WORKING_CAPITAL_INVALID",
                        ", ".join(assessment.missing_evidence),
                    )
                checked_composite_inputs.add(sha256_digest(policy_input))
            allowed_supporting_fields = {
                item.normalized_field
                for item in history
                if any(
                    item.fact_id in policy_input.fact_ids
                    for policy_input in snapshot_composite_inputs
                )
            }
            if not isinstance(manifest, IssuerOperatingReleaseManifestV1):
                allowed_supporting_fields.update(AWARD_FACT_FIELDS)
                models = (
                    (manifest.conditional_reinvestment_policies[0].recipe.model_id,)
                    if manifest.conditional_reinvestment_policies
                    else (manifest.conditional_capital_policies[0].model_id,)
                    if manifest.conditional_capital_policies
                    else (valuation_input_policy.model_id,)
                    if valuation_input_policy is not None
                    else tuple(model.model_id for model in initial_model_specs())
                )
                for model_id in models:
                    profile = valuation_release_requirements(manifest, model_id)
                    if set(profile.required_fact_fields) <= declared_fields:
                        allowed_supporting_fields.update(profile.supporting_fact_fields)
            if (
                not declared_fields
                <= {item.normalized_field for item in history}
                <= declared_fields | allowed_supporting_fields
            ):
                raise DataReleaseError(
                    "DATA_RELEASE_FIELDS_UNAVAILABLE",
                    f"release snapshot {reference.snapshot_id} has undeclared field roles",
                )
            snapshot_ids.append(snapshot.snapshot_id)
            fact_digests.extend(sorted(canonical_fact_digest(fact) for fact in history))
        if checked_composite_inputs != {
            sha256_digest(item) for item in all_composite_inputs
        }:
            raise DataReleaseError(
                "DATA_RELEASE_WORKING_CAPITAL_UNBOUND",
                "every composite input must bind a release source and its mapped facts",
            )
        return (
            tuple(snapshot_ids),
            tuple(sorted(fact_digests)),
            tuple(sorted(set(forecast_digests))),
        )

    def _verify_declared_history(
        self,
        snapshot: SourceSnapshotV1 | IssuerOperatingSourceV1,
        references: tuple[FactRefV1, ...],
        mappings: dict[str, CanonicalMappingV1],
    ) -> tuple[CanonicalFactV1, ...]:
        periods: dict[tuple[object, ...], list[CanonicalFactV1]] = {}
        facts: list[CanonicalFactV1] = []
        for reference in references:
            try:
                fact = self._facts.get(reference.fact_id)
            except Exception as exc:  # pragma: no cover - adapter boundary
                raise DataReleaseError(
                    "DATA_RELEASE_FACT_UNAVAILABLE",
                    f"release fact {reference.fact_id} is unavailable",
                ) from exc
            if canonical_fact_digest(fact) != reference.fact_digest:
                raise DataReleaseError(
                    "DATA_RELEASE_FACT_MISMATCH",
                    f"release fact {reference.fact_id} has a different digest",
                )
            mapping = mappings.get(fact.mapping_decision_id or "")
            if (
                mapping is None
                or mapping.source_concept != fact.concept
                or mapping.normalized_field != fact.normalized_field
                or fact.mapping_confidence != mapping.confidence
            ):
                raise DataReleaseError(
                    "DATA_RELEASE_MAPPING_FACT_MISMATCH",
                    f"release fact {fact.fact_id} does not match a released mapping",
                )
            try:
                verify_accounting_role_evidence(fact, mapping, snapshot)
            except SnapshotError as error:
                raise DataReleaseError(
                    "DATA_RELEASE_ACCOUNTING_ROLE_INVALID",
                    "accounting role evidence differs from the released original",
                ) from error
            key = (
                fact.normalized_field,
                fact.period_start,
                fact.period_end,
                fact.instant,
            )
            periods.setdefault(key, []).append(fact)
            facts.append(fact)
        for candidates in periods.values():
            if candidates[0].normalized_field in AWARD_FACT_FIELDS:
                continue
            try:
                selected = resolve_canonical_facts(
                    candidates,
                    snapshot=snapshot,
                    valuation_timestamp=snapshot.valuation_timestamp,
                    required_fields=(candidates[0].normalized_field,),
                )
            except Exception as exc:  # pragma: no cover - adapter boundary
                raise DataReleaseError(
                    "DATA_RELEASE_CANARY_FAILED",
                    "a declared history period failed point-in-time selection",
                ) from exc
            if {fact.fact_id for fact in selected} != {
                fact.fact_id for fact in candidates
            }:
                raise DataReleaseError(
                    "DATA_RELEASE_FACT_MISMATCH",
                    "a declared history period contains noncanonical candidates",
                )
        return tuple(facts)

    def _resolve_facts(
        self,
        snapshot: SourceSnapshotV1 | IssuerOperatingSourceV1,
        required_fields: tuple[str, ...],
        mappings: dict[str, CanonicalMappingV1],
    ) -> tuple[CanonicalFactV1, ...]:
        try:
            return resolve_canonical_facts(
                (
                    fact
                    for fact in self._facts.list()
                    if fact.mapping_decision_id in mappings
                ),
                snapshot=snapshot,
                valuation_timestamp=snapshot.valuation_timestamp,
                required_fields=required_fields,
            )
        except Exception as exc:  # pragma: no cover - adapter boundary
            raise DataReleaseError(
                "DATA_RELEASE_CANARY_FAILED",
                f"point-in-time canary failed for {snapshot.snapshot_id}",
            ) from exc

    def _verify_issuer_originals(
        self,
        snapshot: IssuerOperatingSourceV1,
        manifest: IssuerOperatingReleaseManifestV1,
    ) -> None:
        try:
            integrities = tuple(
                SecIntegrityEvidenceV1.model_validate_json(
                    self._artifacts.read(ref.artifact_id)
                )
                for ref in manifest.artifact_refs
                if ref.role == "sec-issuer-integrity-v1"
            )
        except ValueError as error:
            raise DataReleaseError(
                "DATA_RELEASE_ORIGINAL_INTEGRITY_INVALID",
                "issuer integrity evidence must satisfy its retained contract",
            ) from error
        contents = {
            ref.content_hash: self._artifacts.read(ref.artifact_id)
            for ref in (*manifest.artifact_refs, *manifest.taxonomy_refs)
        }
        if any(hashlib.sha256(raw).hexdigest() != key for key, raw in contents.items()):
            raise DataReleaseError(
                "DATA_RELEASE_ARTIFACT_HASH_MISMATCH",
                "issuer original artifacts changed during verification",
            )
        for original in snapshot.originals:
            matches = tuple(
                item
                for item in integrities
                if item.accession_number == original.source.accession_number
            )
            if len(matches) != 1:
                raise DataReleaseError(
                    "DATA_RELEASE_ORIGINAL_INTEGRITY_UNAVAILABLE",
                    "each issuer original requires one exact source integrity artifact",
                )
            integrity = matches[0]
            verify_original_integrity(
                original, integrity, parser_version=manifest.parser_version
            )
            require_original_taxonomy(
                integrity.taxonomy_manifest_hash, manifest.taxonomy_refs, contents
            )
            verify_original_bytes(integrity, contents)

    def _verify_mappings(
        self, refs: tuple[MappingRefV1, ...]
    ) -> dict[str, CanonicalMappingV1]:
        mappings = {}
        for reference in refs:
            try:
                mapping = self._mappings.get_mapping(reference.mapping_id)
            except Exception as exc:  # pragma: no cover - adapter boundary
                raise DataReleaseError(
                    "DATA_RELEASE_MAPPING_UNAVAILABLE",
                    f"release mapping {reference.mapping_id} is unavailable",
                ) from exc
            actual = sha256_digest(mapping.model_dump(mode="json"))
            if actual != reference.mapping_digest or mapping.status != "approved":
                raise DataReleaseError(
                    "DATA_RELEASE_MAPPING_HASH_MISMATCH",
                    f"release mapping {reference.mapping_id} failed hash verification",
                )
            mappings[reference.mapping_id] = mapping
        return mappings


class _FilesystemMappingReader:
    def __init__(self, root: Path) -> None:
        self._root = root

    def get_mapping(self, mapping_id: str) -> CanonicalMappingV1:
        path = (self._root / f"{mapping_id}.json").resolve()
        if self._root.resolve() not in path.parents:
            raise ValueError("mapping path escapes repository root")
        return CanonicalMappingV1.model_validate_json(path.read_bytes())


def _load_candidate(
    path: Path,
) -> tuple[DataReleaseManifestV1, DataReleaseVerificationV1]:
    candidate = DataReleaseCandidatePublishRequestV1.model_validate_json(
        path.read_bytes()
    )
    return candidate.manifest, candidate.verification


def main(argv: list[str] | None = None) -> int:
    from .quote_sources import default_quote_providers
    from .free_source_policy import (
        default_macro_providers,
        default_reference_providers,
    )
    from .source_use_deployment import load_runtime_source_use_policy

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--snapshots-root", type=Path, required=True)
    parser.add_argument("--facts-root", type=Path, required=True)
    parser.add_argument("--mappings-root", type=Path, required=True)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--trust-roots", type=Path, required=True)
    parser.add_argument("--policies-root", type=Path)
    args = parser.parse_args(argv)
    try:
        source_use_policy = load_runtime_source_use_policy()
        manifest, verification = _load_candidate(args.candidate)
        report = DataReleaseCanaryRunner(
            snapshot_repository=FilesystemSnapshotRepository(args.snapshots_root),
            fact_repository=FilesystemCanonicalFactRepository(args.facts_root),
            mapping_reader=_FilesystemMappingReader(args.mappings_root),
            artifact_reader=ArtifactStore(args.artifacts_root),
            trust_roots=DataReleaseTrustRootsV1.from_file(args.trust_roots),
            quote_providers=default_quote_providers(),
            macro_providers=default_macro_providers(),
            reference_providers=default_reference_providers(),
            source_use_policy=source_use_policy,
            policy_registry=PolicyRegistry(
                repository=FilesystemPolicyRepository(args.policies_root),
                models=initial_model_specs(),
            )
            if args.policies_root
            else None,
        ).validate(manifest, verification)
    except (OSError, ValueError, DataReleaseError) as exc:
        print(f"data release canary failed: {exc}", file=sys.stderr)
        return 2
    print(canonical_bytes(report).decode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by CLI integration
    raise SystemExit(main())
