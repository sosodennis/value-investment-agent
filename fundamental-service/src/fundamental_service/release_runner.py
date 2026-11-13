"""Read-only validation and canary execution for immutable data releases.

The runner is deliberately independent from the serving application. It reads
immutable repositories, validates the candidate's signed evidence, and runs a
point-in-time fact selection without reading or changing the active pointer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    CanonicalFactV1,
    SecIntegrityEvidenceV1,
    SecHistoryIntegrityEvidenceV1,
    SourceSnapshotV1,
    SourceRecordV1,
)
from .automatic_mapping import verify_automatic_mapping_replay
from .automatic_market_policy_evidence import (
    AUTOMATIC_MARKET_POLICY_ROLE,
    load_release_automatic_market_policy,
    requires_automatic_market_policy,
)
from .data_releases import (
    DataReleaseError,
    AutomaticMappingApprovalV1,
    DataReleaseManifestV1,
    DataReleaseTrustRootsV1,
    DataReleaseVerificationV1,
    FactRefV1,
    MappingRefV1,
    IssuerOperatingReleaseManifestV1,
    verify_data_release_candidate,
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
    AWARD_FACT_FIELDS,
    EQUITY_DILUTION_ARTIFACT_ROLE,
    load_release_dilution_evidence,
)
from .equity_dilution import DilutionError, compute_treasury_stock_dilution
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
from .replay import ArtifactStore
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
    valuation_release_requirements,
    valuation_release_working_capital_inputs,
)


class ReleaseMappingReader(Protocol):
    def get_mapping(self, mapping_id: str) -> CanonicalMappingV1: ...


class ReleaseArtifactReader(Protocol):
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
        if sha256_digest(payload) != self.canary_digest:
            raise ValueError("canary_digest does not match report evidence")
        return self


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
        if isinstance(manifest, IssuerOperatingReleaseManifestV1):
            require_issuer_release_profile(manifest)
        if manifest.valuation_working_capital_policy is not None:
            valuation_release_requirements(
                manifest, manifest.valuation_working_capital_policy.model_id
            )
        self._verify_artifacts(manifest, verification)
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
                        expected_source_revision=verification.source_revision,
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
                    )
                    automatic_policy = load_release_automatic_market_policy(
                        manifest,
                        snapshot=snapshot,
                        policy=policy,
                        admissions=admissions,
                        artifacts=self._artifacts,
                        expected_source_revision=verification.source_revision,
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
        self._verify_automatic_mappings(manifest, verification, mappings)
        checked_snapshots, checked_facts = self._verify_snapshots_and_facts(
            manifest, mappings
        )
        self._verify_equity_dilution(manifest)

        canary_payload = {
            "manifest_digest": manifest.manifest_digest,
            "verification_digest": verification.verification_digest,
            "source_revision": verification.source_revision,
            "snapshots": checked_snapshots,
            "facts": checked_facts,
            "artifacts": self._artifact_digests(manifest, verification),
        }
        if market_policy_checks:
            canary_payload["market_policy_checks"] = tuple(
                sorted(set(market_policy_checks))
            )
        canary_digest = sha256_digest(canary_payload)
        report_payload = {
            "verification": verification,
            "candidate_manifest_digest": manifest.manifest_digest,
            "checked_snapshot_ids": checked_snapshots,
            "checked_fact_digests": checked_facts,
            "checked_artifact_digests": canary_payload["artifacts"],
            "canary_digest": canary_digest,
            "market_policy_checks": tuple(sorted(set(market_policy_checks))),
        }
        return DataReleaseCanaryReportV1.model_validate(report_payload)

    def _verify_automatic_mappings(
        self,
        manifest: DataReleaseManifestV1,
        verification: DataReleaseVerificationV1,
        mappings: dict[str, CanonicalMappingV1],
    ) -> None:
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
                review, mapping, artifacts=self._artifacts
            )
            used = False
            for ref in manifest.snapshot_refs:
                declared = tuple(
                    self._facts.get(item.fact_id)
                    for item in ref.facts
                    if self._facts.get(item.fact_id).mapping_decision_id
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

    def _verify_equity_dilution(self, manifest: DataReleaseManifestV1) -> None:
        references = tuple(
            ref
            for ref in manifest.artifact_refs
            if ref.role == EQUITY_DILUTION_ARTIFACT_ROLE
        )
        has_award_facts = any(
            self._facts.get(ref.fact_id).normalized_field in AWARD_FACT_FIELDS
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
                )
                declared_awards = {
                    fact.fact_id
                    for fact in facts
                    if fact.normalized_field in AWARD_FACT_FIELDS
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
        verification: DataReleaseVerificationV1,
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
                content = self._artifacts.read(reference.artifact_id)
            except Exception as exc:  # pragma: no cover - adapter boundary
                raise DataReleaseError(
                    "DATA_RELEASE_ARTIFACT_UNAVAILABLE",
                    f"release artifact {reference.artifact_id} is unavailable",
                ) from exc
            actual = hashlib.sha256(content).hexdigest()
            if actual != reference.content_hash:
                raise DataReleaseError(
                    "DATA_RELEASE_ARTIFACT_HASH_MISMATCH",
                    f"release artifact {reference.artifact_id} failed hash verification",
                )

    def _artifact_digests(
        self,
        manifest: DataReleaseManifestV1,
        verification: DataReleaseVerificationV1,
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
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        snapshot_ids: list[str] = []
        fact_digests: list[str] = []
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
            resolved = self._resolve_facts(snapshot, base_fields) if base_fields else ()
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
                    (valuation_input_policy.model_id,)
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
        return tuple(snapshot_ids), tuple(sorted(fact_digests))

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
    ) -> tuple[CanonicalFactV1, ...]:
        try:
            return self._facts.resolve(
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
    payload = json.loads(path.read_bytes())
    return (
        DataReleaseManifestV1.model_validate(payload["manifest"]),
        DataReleaseVerificationV1.model_validate(payload["verification"]),
    )


def main(argv: list[str] | None = None) -> int:
    from .quote_sources import default_quote_providers
    from .free_source_policy import (
        default_macro_providers,
        default_reference_providers,
        free_market_source_policy,
    )

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
            source_use_policy=free_market_source_policy(),
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
