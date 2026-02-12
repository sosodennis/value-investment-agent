from __future__ import annotations

from src.common.types import JSONObject
from src.interface.canonical_models import (
    parse_debate_artifact_model,
    parse_financial_reports_model,
    parse_fundamental_artifact_model,
    parse_news_artifact_model,
    parse_technical_artifact_model,
)


def normalize_financial_reports(value: object, context: str) -> list[JSONObject]:
    try:
        return parse_financial_reports_model(value)
    except TypeError as exc:
        raise TypeError(f"{context}: {exc}") from exc


def canonicalize_fundamental_artifact_data(value: object) -> JSONObject:
    return parse_fundamental_artifact_model(value)


def canonicalize_news_artifact_data(value: object) -> JSONObject:
    return parse_news_artifact_model(value)


def canonicalize_debate_artifact_data(value: object) -> JSONObject:
    return parse_debate_artifact_model(value)


def canonicalize_technical_artifact_data(value: object) -> JSONObject:
    return parse_technical_artifact_model(value)
