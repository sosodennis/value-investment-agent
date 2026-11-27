from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .contracts import StrictModel
from .serialization import sha256_digest

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
OriginId = Annotated[str, Field(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")]


class _RecoveryModel(StrictModel):
    model_config = ConfigDict(frozen=True)


class PostgresDatabaseIdentityV1(_RecoveryModel):
    system_identifier: str = Field(min_length=1)
    timeline_id: int = Field(gt=0)
    database_oid: int = Field(gt=0)


class FiscalHistoryOriginV1(PostgresDatabaseIdentityV1):
    origin_id: OriginId


class FiscalIssuanceContextV1(_RecoveryModel):
    origin_id: OriginId


class FiscalHistoryFrontierV1(_RecoveryModel):
    origin_id: OriginId
    covered_through: AwareDatetime
    heads_digest: Digest


class FiscalRecoveryActivationV1(_RecoveryModel):
    committed_at: AwareDatetime
    visible_by: AwareDatetime

    @model_validator(mode="after")
    def ordered(self) -> FiscalRecoveryActivationV1:
        if self.committed_at > self.visible_by:
            raise ValueError("recovery activation clock reversed")
        return self


class FiscalHistoryCutoverV1(_RecoveryModel):
    operation_id: Digest
    source_manifest_digest: Digest
    source_origin_id: OriginId
    target_origin_id: OriginId
    source_frontier_at: AwareDatetime
    source_heads_digest: Digest
    import_writer_xid8: int = Field(gt=0, lt=2**64)
    activation: FiscalRecoveryActivationV1 | None = None

    @model_validator(mode="after")
    def ordered(self) -> FiscalHistoryCutoverV1:
        if self.source_origin_id == self.target_origin_id:
            raise ValueError("recovery source and target origins must differ")
        if self.activation and self.activation.committed_at <= self.source_frontier_at:
            raise ValueError("recovery activation must follow source frontier")
        return self


class FiscalHistoryEpochV1(_RecoveryModel):
    local_origin_id: OriginId
    cutovers: tuple[FiscalHistoryCutoverV1, ...] = ()

    @property
    def issuance_context(self) -> FiscalIssuanceContextV1:
        if self.cutovers and self.cutovers[-1].activation is None:
            raise ValueError("history recovery activation is pending")
        return FiscalIssuanceContextV1(origin_id=self.local_origin_id)

    def require_current_issuance(self, issuance: FiscalIssuanceContextV1) -> None:
        if issuance != self.issuance_context:
            raise ValueError("recovered current evidence requires local issuance")

    def require_current_activity(self, *activity_times: datetime) -> None:
        if not self.cutovers:
            return
        activation = self.cutovers[-1].activation
        if activation is None:
            raise ValueError("history recovery activation is pending")
        if not activity_times or any(
            at.utcoffset() is None or at <= activation.visible_by
            for at in activity_times
        ):
            raise ValueError(
                "recovered current evidence requires fresh issuance and execution"
            )

    @model_validator(mode="after")
    def single_lineage(self) -> FiscalHistoryEpochV1:
        seen: set[str] = set()
        previous: str | None = None
        previous_u: datetime | None = None
        operations: set[str] = set()
        for link in self.cutovers:
            if (
                link.target_origin_id in seen
                or link.source_origin_id == link.target_origin_id
            ):
                raise ValueError("recovery lineage contains a cycle")
            if previous is not None and link.source_origin_id != previous:
                raise ValueError("recovery lineage is discontinuous")
            if previous_u and link.source_frontier_at <= previous_u:
                raise ValueError("recovery frontier clock reversed")
            if previous is not None and previous_u is None:
                raise ValueError("an ancestor recovery activation is pending")
            if link.operation_id in operations:
                raise ValueError("recovery lineage repeats an operation")
            operations.add(link.operation_id)
            seen.add(link.source_origin_id)
            previous = link.target_origin_id
            previous_u = link.activation.visible_by if link.activation else None
        if previous is not None and previous != self.local_origin_id:
            raise ValueError("recovery lineage does not reach the local origin")
        return self


class RecoveryAuthorizationV1(_RecoveryModel):
    protocol: Literal["fundamental-recovery-authorization-v1"] = (
        "fundamental-recovery-authorization-v1"
    )
    manifest_digest: Digest
    source_origin_id: OriginId
    expected_target: PostgresDatabaseIdentityV1
    runtime_role: str = Field(pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    source_fence_reference: str = Field(min_length=1, max_length=1024)

    @property
    def operation_id(self) -> str:
        return sha256_digest(self)
