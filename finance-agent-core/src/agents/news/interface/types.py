from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BeforeValidator

from src.interface.artifacts.artifact_model_shared import (
    symbol,
    to_number,
    to_optional_string,
    to_string,
)

SENTIMENT_MAP: dict[str, str] = {
    "bullish": "bullish",
    "bearish": "bearish",
    "neutral": "neutral",
}

IMPACT_MAP: dict[str, str] = {
    "high": "high",
    "medium": "medium",
    "low": "low",
}

CATEGORY_MAP: dict[str, str] = {
    "general": "general",
    "corporate_event": "corporate_event",
    "corporateevent": "corporate_event",
    "financials": "financials",
    "trusted_news": "trusted_news",
    "trustednews": "trusted_news",
    "analyst_opinion": "analyst_opinion",
    "analystopinion": "analyst_opinion",
    "bullish": "bullish",
    "bearish": "bearish",
}


def _parse_news_text(value: object) -> str:
    return to_string(value, "news text")


def _parse_optional_news_text(value: object) -> str | None:
    return to_optional_string(value, "news optional text")


def _parse_news_number(value: object) -> float:
    return to_number(value, "news number")


def _parse_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        raise TypeError("news string list must be a list")
    return [to_string(item, "news string list[]") for item in value]


def _parse_sentiment(value: object) -> str:
    return symbol(value, "news sentiment", SENTIMENT_MAP)


def _parse_impact(value: object) -> str:
    return symbol(value, "news impact", IMPACT_MAP)


def _parse_category_list(value: object) -> list[str]:
    if not isinstance(value, list):
        raise TypeError("news categories must be a list")
    return [symbol(item, "news categories[]", CATEGORY_MAP) for item in value]


NewsText: TypeAlias = Annotated[str, BeforeValidator(_parse_news_text)]
OptionalNewsText: TypeAlias = Annotated[
    str | None,
    BeforeValidator(_parse_optional_news_text),
]
NewsNumber: TypeAlias = Annotated[float, BeforeValidator(_parse_news_number)]
NewsStringList: TypeAlias = Annotated[list[str], BeforeValidator(_parse_string_list)]
SentimentToken: TypeAlias = Annotated[
    Literal["bullish", "bearish", "neutral"],
    BeforeValidator(_parse_sentiment),
]
ImpactToken: TypeAlias = Annotated[
    Literal["high", "medium", "low"],
    BeforeValidator(_parse_impact),
]
NewsCategoryTokenList: TypeAlias = Annotated[
    list[
        Literal[
            "general",
            "corporate_event",
            "financials",
            "trusted_news",
            "analyst_opinion",
            "bullish",
            "bearish",
        ]
    ],
    BeforeValidator(_parse_category_list),
]
