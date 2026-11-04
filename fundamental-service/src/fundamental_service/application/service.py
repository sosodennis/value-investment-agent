"""Typed application use cases assembled by the HTTP composition root."""

from __future__ import annotations

from dataclasses import dataclass

from ..calculator import CalculationRefusal, calculate, validate
from ..contracts import (
    CalculationArtifactV1,
    SourceSnapshotV1,
    ValidationResponseV1,
    ValuationInputV1,
)
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

    @property
    def ready(self) -> bool:
        return (
            self.snapshot_repository is not None
            and self.artifact_store is not None
            and self.content_store is not None
            and self.config.auth_ready
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
        resolved = validate(value)
        return ValidationResponseV1(
            contract_version="fundamental.v1",
            input=resolved,
            input_digest=resolved.input_digest,
            quality_status=resolved.quality.status,
            issue_codes=resolved.quality.issue_codes,
            missing_evidence=resolved.quality.missing_evidence,
        )

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
