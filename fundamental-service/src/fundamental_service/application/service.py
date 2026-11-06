"""Typed application use cases assembled by the HTTP composition root."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import model_validator

from ..calculator import (
    CalculationRefusal,
    calculate,
    validate,
    with_calculation_result_hash,
)
from ..contracts import (
    ArtifactReferenceV1,
    CalculationArtifactV1,
    CalculationEvidenceV1,
    CalculationTraceV1,
    FactsReadRequestV1,
    FactsReadResponseV1,
    PolicyValuationInputV1,
    QualityStatus,
    SnapshotResolutionRequestV1,
    SnapshotResolutionV1,
    SourceSnapshotV1,
    UncertaintyV1,
    ValidationResponseV1,
    ValuationInputV1,
)
from ..data_releases import ActiveDataReleaseWithManifestV1, DataReleaseError
from ..data_releases import DataReleaseManifestV1
from ..facts import CanonicalFactRepository
from ..governance import ModelInventory
from ..operations import (
    OperationalMetrics,
    OperationsConfig,
    ServiceError,
    guard_calculation_budget,
)
from ..policies import (
    PolicyError,
    PolicyRecordV1,
    PolicyRegistry,
    resolve_policy,
    resolve_policy_overrides,
)
from ..replay import (
    ArtifactRecordV1,
    ReplayEnvelopeV1,
    ReplayReportV1,
    replay_manifest,
)
from ..serialization import is_digest, sha256_digest
from ..snapshots import (
    ContentAddressedStore,
    SnapshotError,
    SnapshotRepository,
)
from ..uncertainty import (
    MonteCarloRequestV1,
    ScenarioV1,
    SensitivityRequestV1,
    UncertaintyEvidenceV1,
    UncertaintyReportV1,
    run_uncertainty,
    validate_uncertainty_controls,
)


class UncertaintyRequestV1(ValuationInputV1):
    """Valuation input with caller-owned uncertainty controls."""

    scenarios: tuple[ScenarioV1, ...] = ()
    sensitivity: tuple[SensitivityRequestV1, ...] = ()
    monte_carlo: MonteCarloRequestV1 | None = None

    @model_validator(mode="after")
    def digest_and_approval(self) -> UncertaintyRequestV1:
        payload = self.model_dump(
            exclude={
                "input_digest",
                "caller_approval",
            }
        )
        computed = sha256_digest(payload)
        if self.input_digest is not None and (
            not is_digest(self.input_digest) or self.input_digest != computed
        ):
            raise ValueError("input_digest does not match complete uncertainty request")
        if (
            self.caller_approval is not None
            and self.caller_approval.input_digest != computed
        ):
            raise ValueError("caller approval is bound to a different input_digest")
        return self

    def base_input(self) -> ValuationInputV1:
        payload = self.model_dump(exclude={"scenarios", "sensitivity", "monte_carlo"})
        payload["input_digest"] = None
        payload["caller_approval"] = None
        return ValuationInputV1.model_validate(payload)

    def with_digest(self) -> UncertaintyRequestV1:
        payload = self.model_dump(exclude={"input_digest", "caller_approval"})
        return self.model_copy(update={"input_digest": sha256_digest(payload)})


def normalize_uncertainty_payload(raw: Mapping[str, object]) -> dict[str, object]:
    """Fold transport wrappers into the canonical uncertainty group before decode."""

    data = dict(raw)
    uncertainty = dict(data.get("uncertainty") or {})
    monte_carlo = data.get("monte_carlo")
    if isinstance(monte_carlo, Mapping):
        monte_spec = monte_carlo.get("uncertainty")
        if isinstance(monte_spec, Mapping):
            if uncertainty.get("mode") not in {None, "none", "monte_carlo"}:
                raise ValueError("uncertainty controls disagree with monte_carlo")
            uncertainty = {**uncertainty, **dict(monte_spec), "mode": "monte_carlo"}
    for field in ("scenarios", "sensitivity"):
        if field in data:
            existing = uncertainty.get(field)
            if existing not in (None, (), []) and existing != data[field]:
                raise ValueError(f"uncertainty controls disagree for {field}")
            uncertainty[field] = data[field]
    data["uncertainty"] = uncertainty
    return data


def _snapshot_error(error: SnapshotError) -> ServiceError:
    if error.code in {
        "SNAPSHOT_NOT_FOUND",
        "ARTIFACT_NOT_FOUND",
        "FACT_NOT_FOUND",
    }:
        return ServiceError(
            error.code,
            "requested immutable evidence was not found",
            status_code=404,
            retryable=False,
        )
    if error.code in {"FACT_CONFLICT", "FACT_AMENDMENT_SCOPE_UNKNOWN"}:
        return ServiceError(
            error.code,
            "canonical fact selection is not verified for this snapshot",
            status_code=422,
            retryable=False,
        )
    return ServiceError(
        error.code,
        "immutable evidence is temporarily unavailable",
        status_code=503,
        retryable=error.retryable or error.code.endswith("UNAVAILABLE"),
    )


def _policy_error(error: PolicyError) -> ServiceError:
    if error.code == "POLICY_NOT_FOUND":
        status_code = 404
        retryable = False
    elif error.code in {
        "POLICY_AMBIGUOUS",
        "CALLER_APPROVAL_CONFLICT",
        "INPUT_DIGEST_MISMATCH",
    }:
        status_code = 409
        retryable = False
    elif error.code == "POLICY_UNAVAILABLE" or error.code.startswith("METADATA_"):
        status_code = 503
        retryable = True
    else:
        status_code = 422
        retryable = False
    return ServiceError(
        error.code,
        str(error),
        status_code=status_code,
        retryable=retryable,
    )


@dataclass(frozen=True)
class FundamentalApplication:
    """Owns use cases while keeping transport and dependency assembly outside."""

    snapshot_repository: SnapshotRepository | None
    artifact_store: Any
    content_store: ContentAddressedStore | None
    config: OperationsConfig
    metrics: OperationalMetrics
    fact_repository: CanonicalFactRepository | None = None
    metadata_store: Any = None
    require_metadata: bool = False
    policy_registry: PolicyRegistry | None = None
    model_inventory: ModelInventory | None = None

    @property
    def ready(self) -> bool:
        return (
            self.snapshot_repository is not None
            and self.artifact_store is not None
            and self.content_store is not None
            and self.fact_repository is not None
            and self.config.auth_ready
            and (
                not self.require_metadata
                or (
                    self.metadata_store is not None
                    and bool(self.metadata_store.ready)
                    and self.model_inventory is not None
                    and self.model_inventory.trust_roots_configured
                )
            )
        )

    def _verify_fact_references(self, value: ValuationInputV1) -> None:
        if self.snapshot_repository is None or self.fact_repository is None:
            raise ServiceError(
                "source_unavailable",
                "canonical fact dependencies are unavailable",
                status_code=503,
                retryable=True,
            )
        snapshot = self.snapshot_repository.get(
            value.valuation_context.data_snapshot_id
        )
        source_hashes = {record.content_hash for record in snapshot.source_records}
        facts = []
        for fact_id in value.historical_facts:
            try:
                fact = self.fact_repository.get(fact_id)
            except SnapshotError as error:
                raise ServiceError(
                    "FACT_NOT_FOUND",
                    "a requested canonical fact is unavailable",
                    status_code=404,
                    retryable=False,
                ) from error
            if (
                fact.issuer_id != snapshot.identity.issuer_id
                or fact.security_id not in {None, snapshot.identity.security_id}
                or getattr(fact.quality, "value", fact.quality) != "verified"
                or fact.available_at > value.valuation_context.valuation_timestamp
                or fact.source.content_hash not in source_hashes
            ):
                raise ServiceError(
                    "FACT_PROVENANCE_MISMATCH",
                    "a requested canonical fact does not belong to the selected "
                    "snapshot",
                    status_code=422,
                    retryable=False,
                )
            facts.append(fact)
        release_manifest = self._data_release_manifest(
            value.valuation_context.data_release_manifest_digest
        )
        if release_manifest is not None:
            self._verify_release_snapshot_and_facts(
                release_manifest,
                snapshot,
                tuple(facts),
                required_fields=(),
            )

    def _data_release_manifest(
        self, manifest_digest: str | None
    ) -> DataReleaseManifestV1 | None:
        if manifest_digest is None:
            if self.require_metadata:
                raise ServiceError(
                    "DATA_RELEASE_MANIFEST_REQUIRED",
                    "production requests require a pinned data release manifest",
                    status_code=422,
                    retryable=False,
                )
            return None
        if self.metadata_store is None:
            raise ServiceError(
                "DATA_RELEASE_UNAVAILABLE",
                "release metadata is unavailable",
                status_code=503,
                retryable=True,
            )
        manifest_reader = getattr(
            self.metadata_store, "get_data_release_manifest", None
        )
        if not callable(manifest_reader):
            raise ServiceError(
                "DATA_RELEASE_UNAVAILABLE",
                "release metadata is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            manifest = manifest_reader(manifest_digest)
        except DataReleaseError as error:
            raise ServiceError(
                error.code,
                "release metadata is temporarily unavailable",
                status_code=503,
                retryable=error.retryable,
            ) from error
        except Exception as error:  # pragma: no cover - persistence boundary
            raise ServiceError(
                "DATA_RELEASE_UNAVAILABLE",
                "release metadata is temporarily unavailable",
                status_code=503,
                retryable=True,
            ) from error
        if manifest is None:
            raise ServiceError(
                "DATA_RELEASE_NOT_FOUND",
                "the pinned data release manifest is unavailable",
                status_code=404,
                retryable=False,
            )
        if manifest.manifest_digest != manifest_digest:
            raise ServiceError(
                "DATA_RELEASE_MANIFEST_MISMATCH",
                "the stored data release does not match the requested digest",
                status_code=409,
                retryable=False,
            )
        return manifest

    @staticmethod
    def _verify_release_snapshot_and_facts(
        manifest: DataReleaseManifestV1,
        snapshot: SourceSnapshotV1,
        facts: tuple[Any, ...],
        *,
        required_fields: tuple[str, ...],
    ) -> None:
        if not set(required_fields).issubset(manifest.required_fields):
            raise ServiceError(
                "DATA_RELEASE_FIELDS_UNAVAILABLE",
                "the pinned release does not cover all requested fields",
                status_code=422,
                retryable=False,
            )
        declared_snapshot = next(
            (
                reference
                for reference in manifest.snapshot_refs
                if reference.snapshot_id == snapshot.snapshot_id
            ),
            None,
        )
        if (
            declared_snapshot is None
            or declared_snapshot.manifest_digest != snapshot.manifest_digest
        ):
            raise ServiceError(
                "DATA_RELEASE_SNAPSHOT_MISMATCH",
                "the snapshot does not match the pinned data release",
                status_code=409,
                retryable=False,
            )
        declared_facts = {
            fact.fact_id: fact.fact_digest for fact in declared_snapshot.facts
        }
        if any(
            fact.fact_id not in declared_facts
            or sha256_digest(fact.model_dump(mode="json"))
            != declared_facts[fact.fact_id]
            for fact in facts
        ):
            raise ServiceError(
                "DATA_RELEASE_FACT_MISMATCH",
                "selected canonical facts do not match the pinned data release",
                status_code=409,
                retryable=False,
            )
        selected_fields = {fact.normalized_field for fact in facts}
        if not set(required_fields).issubset(selected_fields):
            raise ServiceError(
                "DATA_RELEASE_FIELDS_UNAVAILABLE",
                "the pinned release does not contain all requested fields",
                status_code=422,
                retryable=False,
            )

    def _resolve_policy(self, value: ValuationInputV1) -> tuple[ValuationInputV1, Any]:
        if self.policy_registry is None:
            raise ServiceError(
                "POLICY_UNAVAILABLE",
                "no service-owned policy registry is available",
                status_code=503,
                retryable=True,
            )
        try:
            policy = self.policy_registry.select_policy(
                model_id=value.model_id,
                model_version=value.model_version,
                valuation_timestamp=value.valuation_context.valuation_timestamp,
                policy_id=value.policy_id,
            )
            if (
                value.provenance.policy_version is not None
                and value.provenance.policy_version != policy.policy_version
            ):
                raise PolicyError(
                    "POLICY_VERSION_MISMATCH",
                    "request policy version does not match the selected release",
                )
            return resolve_policy(request=value, policy=policy)
        except PolicyError as error:
            raise _policy_error(error) from error
        except ValueError as error:
            raise ServiceError(
                "POLICY_INVALID",
                str(error),
                status_code=422,
                retryable=False,
            ) from error

    def _model_release_issues(self, value: ValuationInputV1) -> tuple[str, ...]:
        if value.model_id not in {"fcff_dcf", "transition_fcff_dcf"}:
            return ("MODEL_FAMILY_NOT_RELEASED",)
        if self.policy_registry is None:
            raise ServiceError(
                "POLICY_UNAVAILABLE",
                "no service-owned model registry is available",
                status_code=503,
                retryable=True,
            )
        model = self.policy_registry.model(value.model_id, value.model_version)
        if model is None:
            return ("MODEL_RELEASE_EVIDENCE_MISSING",)
        issues = []
        if model.lifecycle != "active":
            issues.append("MODEL_NOT_ACTIVE")
        if model.release_manifest is None:
            issues.append("MODEL_RELEASE_EVIDENCE_MISSING")
        return tuple(issues)

    def _require_released_calculator_model(self, value: ValuationInputV1) -> None:
        issues = self._model_release_issues(value)
        if issues:
            raise ServiceError(
                "MODEL_UNSUPPORTED",
                f"model {value.model_id} is not released: {', '.join(issues)}",
                status_code=422,
                retryable=False,
            )

    @staticmethod
    def _trace(
        request: ValuationInputV1,
        result: CalculationArtifactV1,
        snapshot: SourceSnapshotV1,
        resolution: Any,
    ) -> CalculationTraceV1:
        source_hashes = tuple(record.content_hash for record in snapshot.source_records)
        if not is_digest(snapshot.manifest_digest) or any(
            not is_digest(content_hash) for content_hash in source_hashes
        ):
            raise ServiceError(
                "SNAPSHOT_PROVENANCE_INVALID",
                "selected snapshot does not contain verified content hashes",
                status_code=422,
                retryable=False,
            )
        if request.provenance.snapshot_id != snapshot.snapshot_id:
            raise ServiceError(
                "SNAPSHOT_PROVENANCE_MISMATCH",
                "request provenance does not identify the selected snapshot",
                status_code=422,
                retryable=False,
            )
        if not request.historical_facts:
            raise ServiceError(
                "FACT_PROVENANCE_MISSING",
                "calculation evidence requires canonical fact IDs",
                status_code=422,
                retryable=False,
            )
        return CalculationTraceV1(
            source_selection_policy=request.valuation_context.source_selection_policy,
            source_selection_policy_version=snapshot.policy_version,
            snapshot_id=snapshot.snapshot_id,
            snapshot_manifest_digest=snapshot.manifest_digest,
            data_release_manifest_digest=(
                request.valuation_context.data_release_manifest_digest
            ),
            fact_ids=tuple(sorted(request.historical_facts)),
            source_content_hashes=tuple(sorted(source_hashes)),
            policy_id=resolution.policy_id,
            policy_version=resolution.policy_version,
            policy_digest=resolution.policy_digest,
            model_id=request.model_id,
            model_version=request.model_version,
            assumptions_digest=sha256_digest(
                request.assumptions.model_dump(mode="json")
            ),
            calculation_version=result.calculation_version,
        )

    def _persist_evidence(
        self,
        request: ValuationInputV1,
        result: CalculationArtifactV1,
    ) -> CalculationArtifactV1:
        if self.artifact_store is None:
            raise ServiceError(
                "ARTIFACT_UNAVAILABLE",
                "calculation evidence storage is unavailable",
                status_code=503,
                retryable=True,
            )
        trace = result.trace
        if trace is None or result.policy_resolution is None:
            raise ServiceError(
                "CALCULATION_EVIDENCE_INCOMPLETE",
                "calculation evidence trace is incomplete",
                status_code=422,
                retryable=False,
            )
        # Transport correlation IDs are per request; persisted evidence must be
        # byte-stable so the same deterministic result can be safely retried.
        stable_result = result.model_copy(update={"correlation_id": "persisted"})
        evidence_request = request.model_copy(update={"caller_approval": None})
        evidence = CalculationEvidenceV1(
            contract_version="fundamental.v1",
            request=evidence_request,
            calculation=stable_result,
        )
        evidence_digest = sha256_digest(evidence.model_dump(mode="json"))
        artifact_id = f"calculation-evidence-{evidence_digest}"
        dependency_hashes = (
            result.input_digest,
            trace.snapshot_manifest_digest,
            *(
                (trace.data_release_manifest_digest,)
                if trace.data_release_manifest_digest is not None
                else ()
            ),
            *trace.source_content_hashes,
            trace.policy_digest,
            trace.assumptions_digest,
        )
        try:
            record = self.artifact_store.put(
                artifact_id,
                evidence,
                dependency_hashes=dependency_hashes,
                retention="evidence",
            )
        except SnapshotError as error:
            raise _snapshot_error(error) from error
        reference = ArtifactReferenceV1(
            artifact_id=record.artifact_id,
            artifact_type="calculation_evidence",
            content_hash=record.content_hash,
            media_type=record.media_type,
        )
        return with_calculation_result_hash(
            result.model_copy(update={"artifact_references": (reference,)})
        )

    def _persist_uncertainty_evidence(
        self,
        result: UncertaintyReportV1,
        request: dict[str, object],
    ) -> UncertaintyReportV1:
        if self.artifact_store is None:
            raise ServiceError(
                "ARTIFACT_UNAVAILABLE",
                "uncertainty evidence storage is unavailable",
                status_code=503,
                retryable=True,
            )
        trace = result.base.trace
        if trace is None:
            raise ServiceError(
                "UNCERTAINTY_EVIDENCE_INCOMPLETE",
                "uncertainty evidence requires a complete base trace",
                status_code=422,
                retryable=False,
            )
        stable_base = result.base.model_copy(update={"correlation_id": "persisted"})
        stable_result = result.model_copy(
            update={"base": stable_base, "artifact_references": ()}
        )
        evidence = UncertaintyEvidenceV1(request=request, report=stable_result)
        evidence_digest = sha256_digest(evidence.model_dump(mode="json"))
        artifact_id = f"uncertainty-evidence-{evidence_digest}"
        dependencies = (
            result.input_digest,
            result.base.input_digest,
            result.base.result_hash,
            trace.snapshot_manifest_digest,
            *(
                (trace.data_release_manifest_digest,)
                if trace.data_release_manifest_digest is not None
                else ()
            ),
            *trace.source_content_hashes,
            trace.policy_digest,
            trace.assumptions_digest,
        )
        try:
            record = self.artifact_store.put(
                artifact_id,
                evidence,
                dependency_hashes=dependencies,
                retention="evidence",
            )
        except SnapshotError as error:
            raise _snapshot_error(error) from error
        reference = ArtifactReferenceV1(
            artifact_id=record.artifact_id,
            artifact_type="uncertainty_evidence",
            content_hash=record.content_hash,
            media_type=record.media_type,
        )
        returned_base = result.base.model_copy(
            update={
                "artifact_references": (
                    *result.base.artifact_references,
                    reference,
                )
            }
        )
        return result.model_copy(
            update={
                "base": returned_base,
                "artifact_references": (reference,),
            }
        )

    def snapshot(self, snapshot_id: str) -> SourceSnapshotV1:
        if self.snapshot_repository is None:
            self.metrics.increment("source_health_failures_total")
            raise ServiceError(
                "source_unavailable",
                "selected immutable snapshot is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            return self.snapshot_repository.get(snapshot_id)
        except SnapshotError as error:
            self.metrics.increment("source_health_failures_total")
            raise _snapshot_error(error) from error
        except Exception as error:  # pragma: no cover - defensive provider boundary
            self.metrics.increment("source_health_failures_total")
            raise ServiceError(
                "source_unavailable",
                "selected immutable snapshot is unavailable",
                status_code=503,
                retryable=True,
            ) from error

    def read_facts(self, request: FactsReadRequestV1) -> FactsReadResponseV1:
        if self.fact_repository is None:
            raise ServiceError(
                "source_unavailable",
                "canonical fact dependencies are unavailable",
                status_code=503,
                retryable=True,
            )
        snapshot = self.snapshot(request.snapshot_id)
        try:
            facts = self.fact_repository.resolve(
                snapshot=snapshot,
                valuation_timestamp=snapshot.valuation_timestamp,
                required_fields=request.required_fields,
            )
        except SnapshotError as error:
            raise _snapshot_error(error) from error
        release_manifest = self._data_release_manifest(
            request.data_release_manifest_digest
        )
        if release_manifest is not None:
            self._verify_release_snapshot_and_facts(
                release_manifest,
                snapshot,
                facts,
                required_fields=request.required_fields,
            )
        return FactsReadResponseV1(
            contract_version="fundamental.v1",
            snapshot_id=snapshot.snapshot_id,
            data_release_manifest_digest=request.data_release_manifest_digest,
            snapshot_manifest_digest=snapshot.manifest_digest,
            identity=snapshot.identity,
            valuation_timestamp=snapshot.valuation_timestamp,
            quality_status=snapshot.coverage_status,
            issue_codes=tuple(issue.code for issue in snapshot.issues),
            facts=facts,
        )

    def policy(self, policy_id: str) -> PolicyRecordV1:
        if self.policy_registry is None:
            raise ServiceError(
                "POLICY_UNAVAILABLE",
                "service-owned policy registry is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            policy = self.policy_registry.policy(policy_id)
        except PolicyError as error:
            raise _policy_error(error) from error
        except Exception as error:  # pragma: no cover - defensive persistence boundary
            raise ServiceError(
                "POLICY_UNAVAILABLE",
                "service-owned policy release is unavailable",
                status_code=503,
                retryable=True,
            ) from error
        if policy is None:
            raise ServiceError(
                "POLICY_NOT_FOUND",
                "requested policy release was not found",
                status_code=404,
                retryable=False,
            )
        return policy

    def resolve_snapshot(
        self, request: SnapshotResolutionRequestV1
    ) -> SnapshotResolutionV1:
        if self.snapshot_repository is None or self.fact_repository is None:
            raise ServiceError(
                "source_unavailable",
                "snapshot resolution dependencies are unavailable",
                status_code=503,
                retryable=True,
            )
        active_release: ActiveDataReleaseWithManifestV1 | None = None
        if request.release_profile_id is None:
            if self.require_metadata:
                raise ServiceError(
                    "DATA_RELEASE_PROFILE_REQUIRED",
                    "production snapshot resolution requires a release profile",
                    status_code=422,
                    retryable=False,
                )
        else:
            if self.metadata_store is None:
                raise ServiceError(
                    "DATA_RELEASE_UNAVAILABLE",
                    "release metadata is unavailable",
                    status_code=503,
                    retryable=True,
                )
            release_reader = getattr(
                self.metadata_store, "get_active_data_release_with_manifest", None
            )
            if not callable(release_reader):
                raise ServiceError(
                    "DATA_RELEASE_UNAVAILABLE",
                    "release metadata is unavailable",
                    status_code=503,
                    retryable=True,
                )
            try:
                active_release = release_reader(request.release_profile_id)
            except DataReleaseError as error:
                raise ServiceError(
                    error.code,
                    "active data release is temporarily unavailable",
                    status_code=503,
                    retryable=error.retryable,
                ) from error
            if active_release is None:
                raise ServiceError(
                    "DATA_RELEASE_NOT_ACTIVE",
                    "no active data release is available for this profile",
                    status_code=503,
                    retryable=True,
                )
            if not set(request.required_fields).issubset(
                active_release.manifest.required_fields
            ):
                raise ServiceError(
                    "DATA_RELEASE_FIELDS_UNAVAILABLE",
                    "the active release does not cover all required fields",
                    status_code=422,
                    retryable=False,
                )

        candidates = self.snapshot_repository.find(
            identity=request.identity,
            valuation_timestamp=request.valuation_timestamp,
        )
        declared_snapshots = (
            {
                snapshot.snapshot_id: snapshot
                for snapshot in active_release.manifest.snapshot_refs
            }
            if active_release is not None
            else None
        )
        if declared_snapshots is not None:
            candidates = tuple(
                snapshot
                for snapshot in candidates
                if snapshot.snapshot_id in declared_snapshots
            )
        if not candidates:
            raise ServiceError(
                "SNAPSHOT_NOT_FOUND",
                "no immutable snapshot is available for the requested "
                "identity and time",
                status_code=404,
                retryable=False,
            )
        for snapshot in candidates:
            declared_snapshot = (
                None
                if declared_snapshots is None
                else declared_snapshots[snapshot.snapshot_id]
            )
            if (
                declared_snapshot is not None
                and snapshot.manifest_digest != declared_snapshot.manifest_digest
            ):
                raise ServiceError(
                    "DATA_RELEASE_SNAPSHOT_MISMATCH",
                    "a release snapshot does not match its declared manifest",
                    status_code=409,
                    retryable=False,
                )
            try:
                facts = self.fact_repository.resolve(
                    snapshot=snapshot,
                    valuation_timestamp=request.valuation_timestamp,
                    required_fields=request.required_fields,
                )
            except SnapshotError as error:
                if error.code == "FACT_NOT_FOUND":
                    continue
                raise _snapshot_error(error) from error
            if declared_snapshot is not None:
                self._verify_release_snapshot_and_facts(
                    active_release.manifest,
                    snapshot,
                    facts,
                    required_fields=request.required_fields,
                )
            return SnapshotResolutionV1(
                contract_version="fundamental.v1",
                snapshot_id=snapshot.snapshot_id,
                data_release_manifest_digest=(
                    None
                    if active_release is None
                    else active_release.manifest.manifest_digest
                ),
                historical_facts=tuple(fact.fact_id for fact in facts),
                identity=snapshot.identity,
                valuation_timestamp=request.valuation_timestamp,
                source_selection_policy=request.source_selection_policy,
                coverage_profile=request.coverage_profile,
                quality=snapshot.coverage_status,
                issue_codes=tuple(issue.code for issue in snapshot.issues),
                provenance={
                    "snapshot_id": snapshot.snapshot_id,
                    "mapping_version": request.source_selection_policy,
                    "parser_version": snapshot.parser_version,
                    "taxonomy_version": snapshot.taxonomy_manifest_id,
                    "policy_version": snapshot.policy_version,
                    "data_release_manifest_digest": (
                        None
                        if active_release is None
                        else active_release.manifest.manifest_digest
                    ),
                },
            )
        raise ServiceError(
            "FACT_NOT_FOUND",
            "required canonical facts are not available for the requested snapshot",
            status_code=404,
            retryable=False,
        )

    def artifact(self, artifact_id: str) -> ArtifactRecordV1:
        if self.artifact_store is None:
            raise ServiceError(
                "source_unavailable",
                "released artifact is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            return self.artifact_store.get(artifact_id)
        except SnapshotError as error:
            raise _snapshot_error(error) from error

    def artifact_content(self, artifact_id: str) -> tuple[ArtifactRecordV1, bytes]:
        record = self.artifact(artifact_id)
        if self.artifact_store is None:  # pragma: no cover - guarded by artifact()
            raise ServiceError(
                "source_unavailable",
                "released artifact is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            return record, self.artifact_store.read(artifact_id)
        except SnapshotError as error:
            raise _snapshot_error(error) from error

    def validate_valuation(self, value: ValuationInputV1) -> ValidationResponseV1:
        resolved = validate(value)
        resolved, resolution = self._resolve_policy(resolved)
        issue_codes = resolved.quality.issue_codes
        missing_evidence = resolved.quality.missing_evidence
        quality_status = resolved.quality.status
        release_issues = self._model_release_issues(resolved)
        if release_issues:
            quality_status = QualityStatus.UNSUPPORTED
            issue_codes = (*issue_codes, *release_issues)
            missing_evidence = (
                *missing_evidence,
                "complete_model_source_cohort_challenger_calibration_release",
            )
        else:
            self.snapshot(value.valuation_context.data_snapshot_id)
            self._verify_fact_references(value)
        if resolution.selection_mode == "exploratory_active":
            if quality_status is QualityStatus.VERIFIED:
                quality_status = QualityStatus.PROVISIONAL
            issue_codes = (*issue_codes, "POLICY_NOT_PINNED_EXPLORATORY")
            missing_evidence = (*missing_evidence, "caller_pinned_policy_id")
        return ValidationResponseV1(
            contract_version="fundamental.v1",
            input=resolved,
            input_digest=resolved.input_digest,
            quality_status=quality_status,
            policy_resolution=resolution,
            issue_codes=issue_codes,
            missing_evidence=missing_evidence,
        )

    def validate_uncertainty(self, value: UncertaintyRequestV1) -> ValidationResponseV1:
        return self.validate_valuation(value.base_input())

    def calculate_valuation(
        self, value: ValuationInputV1, *, correlation_id: str
    ) -> CalculationArtifactV1 | UncertaintyReportV1:
        self._require_released_calculator_model(value)
        if value.policy_id is None:
            raise ServiceError(
                "POLICY_ID_REQUIRED",
                "verified calculations require an explicit immutable policy_id",
                status_code=422,
                retryable=False,
            )
        resolved, resolution = self._resolve_policy(value)
        return self._calculate_resolved(
            resolved, resolution, correlation_id=correlation_id
        )

    def calculate_with_policy(
        self, value: PolicyValuationInputV1, *, correlation_id: str
    ) -> CalculationArtifactV1 | UncertaintyReportV1:
        if self.policy_registry is None:
            raise ServiceError(
                "POLICY_UNAVAILABLE",
                "no service-owned policy registry is available",
                status_code=503,
                retryable=True,
            )
        try:
            policy = self.policy_registry.select_policy(
                model_id=value.model_id,
                model_version=value.model_version,
                valuation_timestamp=value.valuation_context.valuation_timestamp,
                policy_id=value.policy_id,
            )
        except PolicyError as error:
            raise _policy_error(error) from error
        except Exception as error:  # pragma: no cover - persistence boundary
            raise ServiceError(
                "POLICY_UNAVAILABLE",
                "service-owned policy registry is temporarily unavailable",
                status_code=503,
                retryable=True,
            ) from error
        try:
            resolved, resolution = resolve_policy_overrides(
                request=value, policy=policy
            )
        except PolicyError as error:
            raise _policy_error(error) from error
        return self._calculate_resolved(
            resolved, resolution, correlation_id=correlation_id
        )

    def _calculate_resolved(
        self,
        resolved: ValuationInputV1,
        resolution: Any,
        *,
        correlation_id: str,
    ) -> CalculationArtifactV1 | UncertaintyReportV1:
        if resolution.input_digest != resolved.input_digest:
            raise ServiceError(
                "INPUT_DIGEST_MISMATCH",
                "policy resolution is not bound to the calculation input",
                status_code=409,
                retryable=False,
            )
        self._require_released_calculator_model(resolved)
        guard_calculation_budget(resolved, self.config)
        snapshot = self.snapshot(resolved.valuation_context.data_snapshot_id)
        self._verify_fact_references(resolved)
        has_uncertainty = resolved.uncertainty.mode != "none"
        calculation_input = resolved
        calculation_resolution = resolution
        if has_uncertainty:
            if (
                resolved.caller_approval is not None
                and resolved.caller_approval.decision != "approved"
            ):
                raise ServiceError(
                    "CALLER_APPROVAL_REJECTED",
                    "caller rejected this exact valuation input",
                    status_code=422,
                    retryable=False,
                )
            try:
                validate_uncertainty_controls(resolved)
            except ValueError as error:
                raise ServiceError(
                    "UNCERTAINTY_INVALID",
                    str(error),
                    status_code=422,
                    retryable=False,
                ) from error
            calculation_input = resolved.model_copy(
                update={
                    "uncertainty": UncertaintyV1(mode="none"),
                    "input_digest": None,
                    "caller_approval": None,
                }
            ).with_digest()
            calculation_resolution = resolution.model_copy(
                update={"input_digest": calculation_input.input_digest}
            )
        try:
            result = calculate(calculation_input, correlation_id=correlation_id)
        except CalculationRefusal as error:
            raise ServiceError(
                error.code,
                str(error),
                status_code=422,
                retryable=False,
            ) from error
        trace = self._trace(calculation_input, result, snapshot, calculation_resolution)
        result = with_calculation_result_hash(
            result.model_copy(
                update={"policy_resolution": calculation_resolution, "trace": trace}
            )
        )
        result = self._persist_evidence(calculation_input, result)
        self.metrics.increment("quality_status_total")
        self.metrics.increment(f"quality_status_{result.quality_status.value}_total")
        if not has_uncertainty:
            return result
        try:
            uncertainty = run_uncertainty(resolved, base_result=result)
        except (CalculationRefusal, ValueError) as error:
            raise ServiceError(
                getattr(error, "code", "uncertainty_invalid"),
                str(error),
                status_code=422,
                retryable=False,
            ) from error
        if uncertainty.base.result_hash != result.result_hash:
            raise ServiceError(
                "UNCERTAINTY_BASE_MISMATCH",
                "uncertainty did not use the resolved deterministic calculation",
                status_code=422,
                retryable=False,
            )
        uncertainty_request = resolved.model_dump(
            exclude={"input_digest", "caller_approval"}
        )
        uncertainty = self._persist_uncertainty_evidence(
            uncertainty, uncertainty_request
        )
        self.metrics.increment("quality_status_total")
        self.metrics.increment(f"quality_status_{uncertainty.status.value}_total")
        if uncertainty.status.value in {"abstain", "degraded"}:
            self.metrics.increment("abstention_total")
        return uncertainty

    def replay_valuation(self, envelope: ReplayEnvelopeV1) -> ReplayReportV1:
        if self.artifact_store is None or self.snapshot_repository is None:
            self.metrics.increment("provenance_replay_failures_total")
            raise ServiceError(
                "source_unavailable",
                "replay dependencies are unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            report = replay_manifest(
                envelope,
                artifact_store=self.artifact_store,
                snapshot_repository=self.snapshot_repository,
            )
        except (ValueError, SnapshotError) as error:
            self.metrics.increment("provenance_replay_failures_total")
            if isinstance(error, SnapshotError):
                raise _snapshot_error(error) from error
            raise ServiceError(
                "replay_mismatch",
                "released evidence did not reproduce",
                status_code=422,
                retryable=False,
            ) from error
        if report.status.value in {"abstain", "degraded"}:
            self.metrics.increment("abstention_total")
        return report

    def uncertainty_valuation(self, value: UncertaintyRequestV1) -> UncertaintyReportV1:
        self._require_released_calculator_model(value)
        if value.policy_id is None:
            raise ServiceError(
                "POLICY_ID_REQUIRED",
                "verified uncertainty calculations require an explicit immutable "
                "policy_id",
                status_code=422,
                retryable=False,
            )
        if (
            value.caller_approval is not None
            and value.caller_approval.decision != "approved"
        ):
            raise ServiceError(
                "CALLER_APPROVAL_REJECTED",
                "caller rejected this exact valuation input",
                status_code=422,
                retryable=False,
            )
        try:
            validate_uncertainty_controls(
                value.base_input(),
                scenarios=value.scenarios,
                sensitivity=value.sensitivity,
            )
        except ValueError as error:
            raise ServiceError(
                "UNCERTAINTY_INVALID",
                str(error),
                status_code=422,
                retryable=False,
            ) from error
        guard_calculation_budget(value, self.config)
        self.snapshot(value.valuation_context.data_snapshot_id)
        base_value = value.base_input()
        self._verify_fact_references(base_value)
        deterministic_base = base_value.model_copy(
            update={
                "uncertainty": UncertaintyV1(mode="none"),
                "caller_approval": None,
            }
        ).with_digest()
        resolved, _ = self._resolve_policy(deterministic_base)
        resolved_value = value.model_copy(
            update={
                "policy_id": resolved.policy_id,
                "assumptions": resolved.assumptions,
                "provenance": resolved.provenance,
                "input_digest": None,
                "caller_approval": None,
            }
        ).with_digest()
        if (
            value.caller_approval is not None
            and value.caller_approval.input_digest != resolved_value.input_digest
        ):
            raise ServiceError(
                "CALLER_APPROVAL_CONFLICT",
                "caller approval is bound to a different resolved input_digest",
                status_code=409,
                retryable=False,
            )
        if value.caller_approval is not None:
            resolved_value = resolved_value.model_copy(
                update={"caller_approval": value.caller_approval}
            )
        monte_carlo = value.monte_carlo
        if monte_carlo is not None:
            monte_carlo = monte_carlo.model_copy(
                update={"uncertainty": resolved_value.uncertainty}
            )
        try:
            base = self.calculate_valuation(
                resolved,
                correlation_id="uncertainty-base",
            )
            result = run_uncertainty(
                resolved_value,
                monte_carlo=monte_carlo,
                scenarios=value.scenarios,
                sensitivity=value.sensitivity,
                base_result=base,
                input_digest=resolved_value.input_digest,
            )
        except (CalculationRefusal, ValueError) as error:
            raise ServiceError(
                getattr(error, "code", "uncertainty_invalid"),
                str(error),
                status_code=422,
                retryable=False,
            ) from error
        if result.base.result_hash != base.result_hash:
            raise ServiceError(
                "UNCERTAINTY_BASE_MISMATCH",
                "uncertainty did not use the approved deterministic calculation",
                status_code=422,
                retryable=False,
            )
        result = result.model_copy(update={"base": base})
        evidence_request = resolved_value.model_dump(
            exclude={"input_digest", "caller_approval"}
        )
        result = self._persist_uncertainty_evidence(result, evidence_request)
        self.metrics.increment("quality_status_total")
        self.metrics.increment(f"quality_status_{result.status.value}_total")
        if result.status.value in {"abstain", "degraded"}:
            self.metrics.increment("abstention_total")
        return result


__all__ = ["FundamentalApplication", "UncertaintyRequestV1"]
