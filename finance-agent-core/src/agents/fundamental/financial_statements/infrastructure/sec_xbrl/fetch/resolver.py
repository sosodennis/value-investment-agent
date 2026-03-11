from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Generic, TypeVar

from ..extract.extractor import SearchConfig, SECExtractResult
from ..map.field_resolution_service import (
    calculation_consistency_score,
    clamp_score,
    concept_match_score,
    label_similarity_score,
    presentation_proximity_score,
)
from .extractor_search_processing_service import period_sort_key, statement_matches

T = TypeVar("T")


@dataclass(frozen=True)
class RankedResult:
    result: SECExtractResult
    result_index: int
    period_rank: date
    statement_match: bool
    dimension_preference: int
    concept_match_score: float
    presentation_proximity_score: float
    calculation_consistency_score: float
    label_similarity_score: float
    anchor_confidence_score: float
    concept_priority_score: float
    overall_confidence: float


@dataclass(frozen=True)
class ParsedCandidate(Generic[T]):
    config_index: int
    ranked: RankedResult
    value: T


def rank_results(
    results: list[SECExtractResult],
    config: SearchConfig,
    *,
    field_name: str | None = None,
) -> list[RankedResult]:
    ranked: list[RankedResult] = []
    statement_tokens = [t for t in (config.statement_types or []) if t]

    for idx, result in enumerate(results):
        period_rank = period_sort_key(result.period_key)
        statement_match = (
            True
            if not statement_tokens
            else statement_matches(result.statement, statement_tokens)
        )
        dim_count = len(result.dimension_detail or {})
        if config.type_name == "CONSOLIDATED":
            dimension_preference = 1 if dim_count == 0 else 0
        elif config.type_name == "DIMENSIONAL":
            # For dimensional queries prefer richer dimensional context.
            dimension_preference = dim_count
        else:
            dimension_preference = 0
        concept_score = concept_match_score(
            concept=result.concept,
            concept_regex=config.concept_regex,
        )
        presentation_score = presentation_proximity_score(
            statement_value=result.statement,
            statement_tokens=config.statement_types,
        )
        calculation_score = calculation_consistency_score(
            value=result.value,
            decimals=result.decimals,
            scale=result.scale,
            unit=result.unit,
            period_key=result.period_key,
            explicit_score=result.calculation_score,
        )
        label_score = label_similarity_score(
            label=result.label,
            concept=result.concept,
            field_name=field_name or result.concept,
            concept_regex=config.concept_regex,
        )
        anchor_score = clamp_score(config.anchor_confidence or 0.60)
        concept_priority_score = clamp_score(config.concept_priority)
        overall_confidence = clamp_score(
            (concept_score * 0.32)
            + (presentation_score * 0.22)
            + (calculation_score * 0.20)
            + (label_score * 0.16)
            + (anchor_score * 0.10)
        )
        if statement_match:
            overall_confidence = clamp_score(overall_confidence + 0.04)
        if config.type_name == "CONSOLIDATED" and dim_count == 0:
            overall_confidence = clamp_score(overall_confidence + 0.03)

        ranked.append(
            RankedResult(
                result=result,
                result_index=idx,
                period_rank=period_rank,
                statement_match=statement_match,
                dimension_preference=dimension_preference,
                concept_match_score=concept_score,
                presentation_proximity_score=presentation_score,
                calculation_consistency_score=calculation_score,
                label_similarity_score=label_score,
                anchor_confidence_score=anchor_score,
                concept_priority_score=concept_priority_score,
                overall_confidence=overall_confidence,
            )
        )

    ranked.sort(
        key=lambda item: (
            item.overall_confidence,
            item.concept_match_score,
            item.presentation_proximity_score,
            item.calculation_consistency_score,
            item.label_similarity_score,
            item.anchor_confidence_score,
            item.concept_priority_score,
            item.statement_match,
            item.dimension_preference,
            item.period_rank,
            -item.result_index,
            item.result.concept,
        ),
        reverse=True,
    )
    return ranked


def choose_best_candidate(
    candidates: list[ParsedCandidate[T]],
) -> ParsedCandidate[T] | None:
    if not candidates:
        return None

    return max(
        candidates,
        key=lambda item: (
            item.ranked.overall_confidence,
            item.ranked.concept_match_score,
            item.ranked.presentation_proximity_score,
            item.ranked.calculation_consistency_score,
            item.ranked.label_similarity_score,
            item.ranked.anchor_confidence_score,
            item.ranked.concept_priority_score,
            -item.config_index,
            item.ranked.statement_match,
            item.ranked.dimension_preference,
            item.ranked.period_rank,
            -item.ranked.result_index,
            item.ranked.result.concept,
        ),
    )
