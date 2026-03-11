from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from src.agents.fundamental.subdomains.financial_statements.interface.contracts import (
    FinancialReportModel,
)
from src.agents.fundamental.subdomains.forward_signals.interface.contracts import (
    ForwardSignalPayload,
)


class ReplayBaselineModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    params_dump: dict[str, object] | None = None
    calculation_metrics: dict[str, object] | None = None
    assumptions: list[str] | None = None
    build_metadata: dict[str, object] | None = None
    diagnostics: dict[str, object] | None = None


class ValuationReplayInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["valuation_replay_input_v2"]
    model_type: str
    ticker: str | None = None
    reports: list[FinancialReportModel]
    market_snapshot: dict[str, object] | None = None
    forward_signals: list[ForwardSignalPayload] | None = None
    staleness_mode: Literal["snapshot", "recompute"] = "snapshot"
    override: dict[str, object] | None = None
    baseline: ReplayBaselineModel | None = None

    @field_validator("model_type")
    @classmethod
    def _validate_model_type(cls, value: str) -> str:
        token = value.strip()
        if not token:
            raise ValueError("model_type must be non-empty")
        return token

    @field_validator("reports")
    @classmethod
    def _validate_reports(
        cls, value: list[FinancialReportModel]
    ) -> list[FinancialReportModel]:
        if not value:
            raise ValueError("reports must be non-empty")
        return value


class ValuationReplayCaseRefModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    input_path: str

    @field_validator("case_id", "input_path")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        token = value.strip()
        if not token:
            raise ValueError("value must be non-empty")
        return token


class ValuationReplayManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["valuation_replay_manifest_v1"]
    cases: list[ValuationReplayCaseRefModel]

    @field_validator("cases")
    @classmethod
    def _validate_cases(
        cls, value: list[ValuationReplayCaseRefModel]
    ) -> list[ValuationReplayCaseRefModel]:
        if not value:
            raise ValueError("cases must be non-empty")
        return value


def parse_valuation_replay_input_model(
    value: object, *, context: str
) -> ValuationReplayInputModel:
    try:
        return ValuationReplayInputModel.model_validate(value)
    except ValidationError as exc:
        raise TypeError(f"{context} validation failed: {exc}") from exc


def parse_valuation_replay_manifest_model(
    value: object, *, context: str
) -> ValuationReplayManifestModel:
    try:
        return ValuationReplayManifestModel.model_validate(value)
    except ValidationError as exc:
        raise TypeError(f"{context} validation failed: {exc}") from exc


__all__ = [
    "ReplayBaselineModel",
    "ValuationReplayCaseRefModel",
    "ValuationReplayInputModel",
    "ValuationReplayManifestModel",
    "parse_valuation_replay_input_model",
    "parse_valuation_replay_manifest_model",
]
