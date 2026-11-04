"""Typed application use cases assembled by the HTTP composition root."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import model_validator

from ..calculator import CalculationRefusal, calculate, validate
from ..contracts import (
    CalculationArtifactV1,
    SnapshotResolutionRequestV1,
    SnapshotResolutionV1,
    SourceSnapshotV1,
    ValidationResponseV1,
    ValuationInputV1,
)
from ..facts import CanonicalFactRepository
from ..operations import (
    OperationalMetrics,
    OperationsConfig,
    ServiceError,
    guard_calculation_budget,
)
from ..replay import (
    ArtifactRecordV1,
    ArtifactStore,
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
    UncertaintyReportV1,
    run_uncertainty,
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
                "scenarios",
                "sensitivity",
                "monte_carlo",
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
        return ValuationInputV1.model_validate(
            self.model_dump(exclude={"scenarios", "sensitivity", "monte_carlo"})
        )


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
    if error.code in {"SNAPSHOT_NOT_FOUND", "ARTIFACT_NOT_FOUND"}:
        return ServiceError(
            error.code,
            "requested immutable evidence was not found",
            status_code=404,
            retryable=False,
        )
    return ServiceError(
        error.code,
        "immutable evidence is temporarily unavailable",
        status_code=503,
        retryable=error.retryable or error.code.endswith("UNAVAILABLE"),
    )


@dataclass(frozen=True)
class FundamentalApplication:
    """Owns use cases while keeping transport and dependency assembly outside."""

    snapshot_repository: SnapshotRepository | None
    artifact_store: ArtifactStore | None
    content_store: ContentAddressedStore | None
    config: OperationsConfig
    metrics: OperationalMetrics
    fact_repository: CanonicalFactRepository | None = None

    @property
    def ready(self) -> bool:
        return (
            self.snapshot_repository is not None
            and self.artifact_store is not None
            and self.content_store is not None
            and self.fact_repository is not None
            and self.config.auth_ready
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
        candidates = self.snapshot_repository.find(
            identity=request.identity,
            valuation_timestamp=request.valuation_timestamp,
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
            return SnapshotResolutionV1(
                contract_version="fundamental.v1",
                snapshot_id=snapshot.snapshot_id,
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
        self.snapshot(value.valuation_context.data_snapshot_id)
        self._verify_fact_references(value)
        resolved = validate(value)
        return ValidationResponseV1(
            contract_version="fundamental.v1",
            input=resolved,
            input_digest=resolved.input_digest,
            quality_status=resolved.quality.status,
            issue_codes=resolved.quality.issue_codes,
            missing_evidence=resolved.quality.missing_evidence,
        )

    def validate_uncertainty(self, value: UncertaintyRequestV1) -> ValidationResponseV1:
        return self.validate_valuation(value.base_input())

    def calculate_valuation(
        self, value: ValuationInputV1, *, correlation_id: str
    ) -> CalculationArtifactV1:
        guard_calculation_budget(value, self.config)
        self.snapshot(value.valuation_context.data_snapshot_id)
        try:
            result = calculate(value, correlation_id=correlation_id)
        except CalculationRefusal as error:
            raise ServiceError(
                error.code,
                str(error),
                status_code=422,
                retryable=False,
            ) from error
        self.metrics.increment("quality_status_total")
        self.metrics.increment(f"quality_status_{result.quality_status.value}_total")
        return result

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
        guard_calculation_budget(value, self.config)
        self.snapshot(value.valuation_context.data_snapshot_id)
        try:
            result = run_uncertainty(
                value,
                monte_carlo=value.monte_carlo,
                scenarios=value.scenarios,
                sensitivity=value.sensitivity,
            )
        except (CalculationRefusal, ValueError) as error:
            raise ServiceError(
                getattr(error, "code", "uncertainty_invalid"),
                str(error),
                status_code=422,
                retryable=False,
            ) from error
        self.metrics.increment("quality_status_total")
        self.metrics.increment(f"quality_status_{result.status.value}_total")
        if result.status.value in {"abstain", "degraded"}:
            self.metrics.increment("abstention_total")
        return result


__all__ = ["FundamentalApplication", "UncertaintyRequestV1"]
