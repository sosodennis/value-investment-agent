from __future__ import annotations

import logging
from typing import TypeVar, cast

from src.agents.fundamental.shared.contracts.traceable import (
    ManualProvenance,
    TraceableField,
    XBRLProvenance,
)
from src.shared.kernel.tools.logger import log_event

from .extractor import SearchConfig, SECReportExtractor
from .field_resolution_utils import (
    as_dimensional_configs,
    as_relaxed_context_configs,
    parse_numeric,
    parse_scale,
    preview_value,
    search_config_key,
)
from .resolver import ParsedCandidate, choose_best_candidate, rank_results

T = TypeVar("T")


def collect_parsed_candidates(
    *,
    extractor: SECReportExtractor,
    configs: list[SearchConfig],
    name: str,
    target_type: type[T],
    logger_: logging.Logger,
) -> list[ParsedCandidate[T]]:
    parsed_candidates: list[ParsedCandidate[T]] = []

    for config_index, config in enumerate(configs):
        results = extractor.search(config)
        if not results:
            log_event(
                logger_,
                event="fundamental_xbrl_field_no_matches",
                message="no xbrl matches for field under config",
                level=logging.DEBUG,
                fields={"field_name": name, "concept_regex": config.concept_regex},
            )
            continue

        for ranked in rank_results(results, config, field_name=name):
            res = ranked.result
            raw_val = res.value

            if raw_val is None:
                log_event(
                    logger_,
                    event="fundamental_xbrl_field_skip_empty",
                    message="skip empty xbrl value",
                    level=logging.DEBUG,
                    fields={
                        "field_name": name,
                        "concept": res.concept,
                        "period_key": res.period_key,
                    },
                )
                continue

            if target_type is float:
                scale = parse_scale(res.scale)
                parsed = parse_numeric(raw_val, scale)
                if parsed is None:
                    log_event(
                        logger_,
                        event="fundamental_xbrl_field_skip_non_numeric",
                        message="skip non-numeric xbrl value",
                        level=logging.DEBUG,
                        fields={
                            "field_name": name,
                            "concept": res.concept,
                            "period_key": res.period_key,
                            "statement": res.statement,
                            "value_preview": preview_value(raw_val),
                        },
                    )
                    continue
                val = cast(T, parsed)
            else:
                try:
                    val = cast(T, target_type(raw_val))
                except (ValueError, TypeError):
                    log_event(
                        logger_,
                        event="fundamental_xbrl_field_skip_non_castable",
                        message="skip non-castable xbrl value",
                        level=logging.DEBUG,
                        fields={
                            "field_name": name,
                            "concept": res.concept,
                            "period_key": res.period_key,
                            "value_preview": preview_value(raw_val),
                        },
                    )
                    continue

            parsed_candidates.append(
                ParsedCandidate(
                    config_index=config_index,
                    ranked=ranked,
                    value=val,
                )
            )

    return parsed_candidates


def build_resolution_stages(
    configs: list[SearchConfig],
) -> list[tuple[str, list[SearchConfig]]]:
    strict_primary = list(configs)
    strict_dimensional = as_dimensional_configs(configs)
    relaxed_context = as_relaxed_context_configs(configs, strict_dimensional)

    planned: list[tuple[str, list[SearchConfig]]] = [
        ("strict_primary", strict_primary),
        ("strict_dimensional", strict_dimensional),
        ("relaxed_context", relaxed_context),
    ]

    stages: list[tuple[str, list[SearchConfig]]] = []
    seen_keys: set[tuple[object, ...]] = set()
    for stage_name, stage_configs in planned:
        unique_stage_configs: list[SearchConfig] = []
        for cfg in stage_configs:
            key = search_config_key(cfg)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique_stage_configs.append(cfg)
        if unique_stage_configs:
            stages.append((stage_name, unique_stage_configs))
    return stages


def extract_field(
    *,
    extractor: SECReportExtractor,
    configs: list[SearchConfig],
    name: str,
    target_type: type[T] = float,
    logger_: logging.Logger,
) -> TraceableField[T]:
    stages = build_resolution_stages(configs)

    for stage_name, stage_configs in stages:
        parsed_candidates = collect_parsed_candidates(
            extractor=extractor,
            configs=stage_configs,
            name=name,
            target_type=target_type,
            logger_=logger_,
        )
        selected = choose_best_candidate(parsed_candidates)
        if selected is None:
            continue

        selected_result = selected.ranked.result
        log_event(
            logger_,
            event="fundamental_xbrl_field_hit",
            message="xbrl field hit",
            fields={
                "field_name": name,
                "concept": selected_result.concept,
                "period_key": selected_result.period_key,
                "value_preview": preview_value(selected_result.value),
                "selected_config_index": selected.config_index,
                "selected_result_index": selected.ranked.result_index,
                "resolution_stage": stage_name,
                "resolution_confidence": round(selected.ranked.overall_confidence, 4),
                "concept_match_score": round(selected.ranked.concept_match_score, 4),
                "presentation_proximity_score": round(
                    selected.ranked.presentation_proximity_score, 4
                ),
                "calculation_consistency_score": round(
                    selected.ranked.calculation_consistency_score, 4
                ),
                "label_similarity_score": round(
                    selected.ranked.label_similarity_score, 4
                ),
                "anchor_confidence_score": round(
                    selected.ranked.anchor_confidence_score, 4
                ),
            },
        )

        provenance = XBRLProvenance(
            concept=selected_result.concept,
            period=selected_result.period_key,
            resolution_stage=stage_name,
            confidence=round(selected.ranked.overall_confidence, 4),
        )
        return TraceableField(name=name, value=selected.value, provenance=provenance)

    tags_searched = [c.concept_regex for c in configs]
    stages_searched = [stage_name for stage_name, _stage in stages]
    return TraceableField(
        name=name,
        value=None,
        provenance=ManualProvenance(
            description=(
                "Not found in XBRL. "
                f"Searched tags: {tags_searched}; stages: {stages_searched}"
            )
        ),
    )
