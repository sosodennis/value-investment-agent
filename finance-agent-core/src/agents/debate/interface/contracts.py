from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from src.interface.artifact_model_shared import (
    symbol,
    to_json,
    to_number,
    to_optional_number,
    to_optional_string,
    to_string,
)

RISK_PROFILE_MAP: dict[str, str] = {
    "DEFENSIVE_VALUE": "DEFENSIVE_VALUE",
    "GROWTH_TECH": "GROWTH_TECH",
    "SPECULATIVE_CRYPTO_BIO": "SPECULATIVE_CRYPTO_BIO",
}

VERDICT_MAP: dict[str, str] = {
    "STRONG_LONG": "STRONG_LONG",
    "LONG": "LONG",
    "NEUTRAL": "NEUTRAL",
    "AVOID": "AVOID",
    "SHORT": "SHORT",
    "STRONG_SHORT": "STRONG_SHORT",
}

PRICE_IMPLICATION_MAP: dict[str, str] = {
    "SURGE": "SURGE",
    "MODERATE_UP": "MODERATE_UP",
    "FLAT": "FLAT",
    "MODERATE_DOWN": "MODERATE_DOWN",
    "CRASH": "CRASH",
}

SOURCE_TYPE_MAP: dict[str, str] = {
    "financials": "financials",
    "news": "news",
    "technicals": "technicals",
}

SOURCE_WEIGHT_MAP: dict[str, str] = {
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
}


class ScenarioModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    probability: float
    outcome_description: str
    price_implication: Literal["SURGE", "MODERATE_UP", "FLAT", "MODERATE_DOWN", "CRASH"]

    @field_validator("probability", mode="before")
    @classmethod
    def _probability(cls, value: object) -> float:
        return to_number(value, "scenario.probability")

    @field_validator("outcome_description", mode="before")
    @classmethod
    def _outcome(cls, value: object) -> str:
        return to_string(value, "scenario.outcome_description")

    @field_validator("price_implication", mode="before")
    @classmethod
    def _price_implication(cls, value: object) -> str:
        return symbol(
            value,
            "scenario.price_implication",
            PRICE_IMPLICATION_MAP,
            uppercase=True,
        )


class DebateHistoryMessageModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    role: str | None = None
    content: str

    @field_validator("name", "role", mode="before")
    @classmethod
    def _optional_name_role(cls, value: object) -> str | None:
        return to_optional_string(value, "debate history field")

    @field_validator("content", mode="before")
    @classmethod
    def _content(cls, value: object) -> str:
        if value is None:
            raise TypeError("debate history.content is required")
        return to_string(str(value), "debate history.content")


class EvidenceFactModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fact_id: str
    source_type: Literal["financials", "news", "technicals"]
    source_weight: Literal["HIGH", "MEDIUM", "LOW"]
    summary: str
    value: str | float | int | None = None
    units: str | None = None
    period: str | None = None
    provenance: dict[str, object] | None = None

    @field_validator("fact_id", "summary", mode="before")
    @classmethod
    def _required_text(cls, value: object) -> str:
        return to_string(value, "evidence fact text")

    @field_validator("source_type", mode="before")
    @classmethod
    def _source_type(cls, value: object) -> str:
        return symbol(value, "evidence.source_type", SOURCE_TYPE_MAP)

    @field_validator("source_weight", mode="before")
    @classmethod
    def _source_weight(cls, value: object) -> str:
        return symbol(
            value, "evidence.source_weight", SOURCE_WEIGHT_MAP, uppercase=True
        )

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

    @field_validator("units", "period", mode="before")
    @classmethod
    def _optional_text(cls, value: object) -> str | None:
        return to_optional_string(value, "evidence optional text")

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
    risk_profile: Literal["DEFENSIVE_VALUE", "GROWTH_TECH", "SPECULATIVE_CRYPTO_BIO"]
    final_verdict: Literal[
        "STRONG_LONG", "LONG", "NEUTRAL", "AVOID", "SHORT", "STRONG_SHORT"
    ]
    winning_thesis: str
    primary_catalyst: str
    primary_risk: str
    supporting_factors: list[str]
    debate_rounds: int
    rr_ratio: float | None = None
    alpha: float | None = None
    risk_free_benchmark: float | None = None
    raw_ev: float | None = None
    conviction: float | None = None
    analysis_bias: str | None = None
    model_summary: str | None = None
    data_quality_warning: bool | None = None
    history: list[DebateHistoryMessageModel] | None = None
    facts: list[EvidenceFactModel] | None = None

    @field_validator("risk_profile", mode="before")
    @classmethod
    def _risk_profile(cls, value: object) -> str:
        return symbol(value, "debate.risk_profile", RISK_PROFILE_MAP, uppercase=True)

    @field_validator("final_verdict", mode="before")
    @classmethod
    def _final_verdict(cls, value: object) -> str:
        return symbol(value, "debate.final_verdict", VERDICT_MAP, uppercase=True)

    @field_validator(
        "winning_thesis",
        "primary_catalyst",
        "primary_risk",
        "analysis_bias",
        "model_summary",
        mode="before",
    )
    @classmethod
    def _text_fields(cls, value: object) -> str | None:
        return to_optional_string(value, "debate text")

    @field_validator("supporting_factors", mode="before")
    @classmethod
    def _supporting(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise TypeError("debate.supporting_factors must be a list")
        return [to_string(item, "debate.supporting_factors[]") for item in value]

    @field_validator("debate_rounds", mode="before")
    @classmethod
    def _rounds(cls, value: object) -> int:
        return int(to_number(value, "debate.debate_rounds"))

    @field_validator(
        "rr_ratio",
        "alpha",
        "risk_free_benchmark",
        "raw_ev",
        "conviction",
        mode="before",
    )
    @classmethod
    def _optional_numeric(cls, value: object) -> float | None:
        return to_optional_number(value, "debate.optional_number")

    @field_validator("data_quality_warning", mode="before")
    @classmethod
    def _data_quality_warning(cls, value: object) -> bool | None:
        if value is None:
            return None
        if not isinstance(value, bool):
            raise TypeError("debate.data_quality_warning must be a boolean")
        return value
