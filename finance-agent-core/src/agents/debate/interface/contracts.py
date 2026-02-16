from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from src.interface.artifacts.artifact_model_shared import (
    to_json,
    validate_and_dump,
)
from src.shared.kernel.types import JSONObject

from .types import (
    DebateFinalVerdict,
    DebateRiskProfile,
    DebateRounds,
    EvidenceFactText,
    EvidenceOptionalText,
    EvidenceSourceType,
    EvidenceSourceWeight,
    HistoryContent,
    HistoryOptionalText,
    OptionalDebateNumber,
    OptionalDebateText,
    ScenarioOutcomeDescription,
    ScenarioPriceImplication,
    ScenarioProbability,
    SupportingFactors,
)


class ScenarioModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    probability: ScenarioProbability
    outcome_description: ScenarioOutcomeDescription
    price_implication: ScenarioPriceImplication


class DebateHistoryMessageModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: HistoryOptionalText = None
    role: HistoryOptionalText = None
    content: HistoryContent


class EvidenceFactModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fact_id: EvidenceFactText
    source_type: EvidenceSourceType
    source_weight: EvidenceSourceWeight
    summary: EvidenceFactText
    value: str | float | int | None = None
    units: EvidenceOptionalText = None
    period: EvidenceOptionalText = None
    provenance: dict[str, object] | None = None

    @field_validator("value", mode="before")
    @classmethod
    def _value(cls, value: object) -> str | float | int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise TypeError("evidence.value cannot be boolean")
        if isinstance(value, str):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise TypeError("evidence.value must be finite")
            return value
        raise TypeError("evidence.value must be string | number | null")

    @field_validator("provenance", mode="before")
    @classmethod
    def _provenance(cls, value: object) -> dict[str, object] | None:
        if value is None:
            return None
        parsed = to_json(value, "evidence.provenance")
        if not isinstance(parsed, dict):
            raise TypeError("evidence.provenance must serialize to an object")
        return parsed


class DebateArtifactModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scenario_analysis: dict[
        Literal["bull_case", "bear_case", "base_case"], ScenarioModel
    ]
    risk_profile: DebateRiskProfile
    final_verdict: DebateFinalVerdict
    winning_thesis: OptionalDebateText
    primary_catalyst: OptionalDebateText
    primary_risk: OptionalDebateText
    supporting_factors: SupportingFactors
    debate_rounds: DebateRounds
    rr_ratio: OptionalDebateNumber = None
    alpha: OptionalDebateNumber = None
    risk_free_benchmark: OptionalDebateNumber = None
    raw_ev: OptionalDebateNumber = None
    conviction: OptionalDebateNumber = None
    analysis_bias: OptionalDebateText = None
    model_summary: OptionalDebateText = None
    data_quality_warning: bool | None = None
    history: list[DebateHistoryMessageModel] | None = None
    facts: list[EvidenceFactModel] | None = None

    @field_validator("data_quality_warning", mode="before")
    @classmethod
    def _data_quality_warning(cls, value: object) -> bool | None:
        if value is None:
            return None
        if not isinstance(value, bool):
            raise TypeError("debate.data_quality_warning must be a boolean")
        return value


def parse_debate_artifact_model(value: object) -> JSONObject:
    return validate_and_dump(
        DebateArtifactModel,
        value,
        "debate artifact",
        exclude_none=True,
    )
