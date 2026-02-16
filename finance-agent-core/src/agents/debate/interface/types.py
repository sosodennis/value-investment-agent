from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BeforeValidator

from src.interface.artifacts.artifact_model_shared import (
    symbol,
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


def _parse_probability(value: object) -> float:
    return to_number(value, "scenario.probability")


def _parse_outcome(value: object) -> str:
    return to_string(value, "scenario.outcome_description")


def _parse_price_implication(value: object) -> str:
    return symbol(
        value,
        "scenario.price_implication",
        PRICE_IMPLICATION_MAP,
        uppercase=True,
    )


def _parse_optional_name_role(value: object) -> str | None:
    return to_optional_string(value, "debate history field")


def _parse_history_content(value: object) -> str:
    if value is None:
        raise TypeError("debate history.content is required")
    return to_string(str(value), "debate history.content")


def _parse_fact_text(value: object) -> str:
    return to_string(value, "evidence fact text")


def _parse_source_type(value: object) -> str:
    return symbol(value, "evidence.source_type", SOURCE_TYPE_MAP)


def _parse_source_weight(value: object) -> str:
    return symbol(value, "evidence.source_weight", SOURCE_WEIGHT_MAP, uppercase=True)


def _parse_optional_fact_text(value: object) -> str | None:
    return to_optional_string(value, "evidence optional text")


def _parse_risk_profile(value: object) -> str:
    return symbol(value, "debate.risk_profile", RISK_PROFILE_MAP, uppercase=True)


def _parse_final_verdict(value: object) -> str:
    return symbol(value, "debate.final_verdict", VERDICT_MAP, uppercase=True)


def _parse_optional_debate_text(value: object) -> str | None:
    return to_optional_string(value, "debate text")


def _parse_supporting_factors(value: object) -> list[str]:
    if not isinstance(value, list):
        raise TypeError("debate.supporting_factors must be a list")
    return [to_string(item, "debate.supporting_factors[]") for item in value]


def _parse_debate_rounds(value: object) -> int:
    return int(to_number(value, "debate.debate_rounds"))


def _parse_optional_debate_number(value: object) -> float | None:
    return to_optional_number(value, "debate.optional_number")


ScenarioProbability: TypeAlias = Annotated[float, BeforeValidator(_parse_probability)]
ScenarioOutcomeDescription: TypeAlias = Annotated[
    str,
    BeforeValidator(_parse_outcome),
]
ScenarioPriceImplication: TypeAlias = Annotated[
    Literal["SURGE", "MODERATE_UP", "FLAT", "MODERATE_DOWN", "CRASH"],
    BeforeValidator(_parse_price_implication),
]
HistoryOptionalText: TypeAlias = Annotated[
    str | None,
    BeforeValidator(_parse_optional_name_role),
]
HistoryContent: TypeAlias = Annotated[
    str,
    BeforeValidator(_parse_history_content),
]

EvidenceFactText: TypeAlias = Annotated[str, BeforeValidator(_parse_fact_text)]
EvidenceSourceType: TypeAlias = Annotated[
    Literal["financials", "news", "technicals"],
    BeforeValidator(_parse_source_type),
]
EvidenceSourceWeight: TypeAlias = Annotated[
    Literal["HIGH", "MEDIUM", "LOW"],
    BeforeValidator(_parse_source_weight),
]
EvidenceOptionalText: TypeAlias = Annotated[
    str | None,
    BeforeValidator(_parse_optional_fact_text),
]

DebateRiskProfile: TypeAlias = Annotated[
    Literal["DEFENSIVE_VALUE", "GROWTH_TECH", "SPECULATIVE_CRYPTO_BIO"],
    BeforeValidator(_parse_risk_profile),
]
DebateFinalVerdict: TypeAlias = Annotated[
    Literal["STRONG_LONG", "LONG", "NEUTRAL", "AVOID", "SHORT", "STRONG_SHORT"],
    BeforeValidator(_parse_final_verdict),
]
OptionalDebateText: TypeAlias = Annotated[
    str | None,
    BeforeValidator(_parse_optional_debate_text),
]
SupportingFactors: TypeAlias = Annotated[
    list[str],
    BeforeValidator(_parse_supporting_factors),
]
DebateRounds: TypeAlias = Annotated[int, BeforeValidator(_parse_debate_rounds)]
OptionalDebateNumber: TypeAlias = Annotated[
    float | None,
    BeforeValidator(_parse_optional_debate_number),
]
