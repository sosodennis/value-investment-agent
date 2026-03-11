from __future__ import annotations

import re
from dataclasses import replace

from ..extract.extractor import SearchConfig


def as_dimensional_configs(configs: list[SearchConfig]) -> list[SearchConfig]:
    dimensional: list[SearchConfig] = []
    for cfg in configs:
        if cfg.type_name == "DIMENSIONAL":
            dimensional.append(cfg)
            continue
        dimensional.append(
            SearchConfig(
                concept_regex=cfg.concept_regex,
                type_name="DIMENSIONAL",
                dimension_regex=cfg.dimension_regex or ".*",
                statement_types=cfg.statement_types,
                period_type=cfg.period_type,
                unit_whitelist=cfg.unit_whitelist,
                unit_blacklist=cfg.unit_blacklist,
                respect_anchor_date=cfg.respect_anchor_date,
                concept_priority=cfg.concept_priority,
                anchor_confidence=cfg.anchor_confidence,
                mapping_source=cfg.mapping_source,
            )
        )
    return dimensional


def as_relaxed_context_configs(
    configs: list[SearchConfig], dimensional_configs: list[SearchConfig]
) -> list[SearchConfig]:
    relaxed: list[SearchConfig] = []
    for cfg in [*configs, *dimensional_configs]:
        relaxed.append(
            SearchConfig(
                concept_regex=cfg.concept_regex,
                type_name=cfg.type_name,
                dimension_regex=cfg.dimension_regex,
                statement_types=None,
                period_type=cfg.period_type,
                unit_whitelist=cfg.unit_whitelist,
                unit_blacklist=cfg.unit_blacklist,
                respect_anchor_date=False,
                concept_priority=cfg.concept_priority,
                anchor_confidence=cfg.anchor_confidence,
                mapping_source=cfg.mapping_source,
            )
        )
    return relaxed


def enrich_configs_with_resolution_metadata(
    *,
    configs: list[SearchConfig],
    source: str,
    anchor_source: str | None,
    anchor_rule_count: int,
) -> list[SearchConfig]:
    enriched: list[SearchConfig] = []
    base_anchor_confidence = _anchor_source_confidence(anchor_source)
    source_boost = _mapping_source_confidence_boost(source)
    for index, config in enumerate(configs):
        concept_priority = max(0.35, 1.0 - (float(index) * 0.08))
        anchor_confidence = config.anchor_confidence
        if anchor_confidence is None:
            effective = base_anchor_confidence + source_boost
            if anchor_rule_count > 0 and index >= anchor_rule_count:
                effective -= 0.25
            anchor_confidence = clamp_score(effective)
        enriched.append(
            replace(
                config,
                concept_priority=concept_priority,
                anchor_confidence=clamp_score(anchor_confidence),
                mapping_source=source,
            )
        )
    return enriched


def search_config_key(config: SearchConfig) -> tuple[object, ...]:
    return (
        config.concept_regex,
        config.type_name,
        config.dimension_regex,
        tuple(config.statement_types or []),
        config.period_type,
        tuple(config.unit_whitelist or []),
        tuple(config.unit_blacklist or []),
        config.respect_anchor_date,
    )


def parse_numeric(raw_val: object, scale: int | None = None) -> float | None:
    if isinstance(raw_val, int | float):
        value = float(raw_val)
        return value * (10**scale) if scale else value
    if not isinstance(raw_val, str):
        return None

    text = raw_val.strip().replace(",", "").replace("\u00a0", "")
    if not text:
        return None

    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"

    if "<" in text or ">" in text:
        return None

    pattern = r"^[-+]?((\d+(\.\d*)?)|(\.\d+))([eE][-+]?\d+)?$"
    if not re.match(pattern, text):
        return None

    try:
        value = float(text)
        return value * (10**scale) if scale else value
    except (ValueError, TypeError):
        return None


def parse_scale(scale: object) -> int | None:
    if scale is None:
        return None
    try:
        return int(scale)
    except (ValueError, TypeError):
        return None


def preview_value(raw_val: object, max_len: int = 80) -> str:
    text = str(raw_val).replace("\n", " ").strip()
    if len(text) > max_len:
        return f"{text[:max_len]}..."
    return text


def concept_match_score(*, concept: str, concept_regex: str) -> float:
    normalized_concept = concept.strip().lower()
    normalized_pattern = concept_regex.strip().lower()
    if not normalized_concept or not normalized_pattern:
        return 0.0
    if normalized_concept == normalized_pattern:
        return 1.0
    if _local_name(normalized_concept) == _local_name(normalized_pattern):
        return 0.92

    regex_score = _regex_match_score(normalized_concept, normalized_pattern)
    if regex_score > 0.0:
        return regex_score

    concept_tokens = _tokenize_text(_local_name(normalized_concept))
    pattern_tokens = _tokenize_text(_local_name(_regex_to_text(normalized_pattern)))
    overlap = _token_overlap(concept_tokens, pattern_tokens)
    return clamp_score(0.30 + (0.55 * overlap))


def presentation_proximity_score(
    *,
    statement_value: str | None,
    statement_tokens: list[str] | None,
) -> float:
    tokens = [token.lower() for token in (statement_tokens or []) if token]
    if not tokens:
        return 0.55
    if not statement_value:
        return 0.25

    statement_text = statement_value.lower()
    if any(token in statement_text for token in tokens):
        return 1.0

    statement_terms = _tokenize_text(statement_text)
    token_terms = set().union(*(_tokenize_text(token) for token in tokens))
    overlap = _token_overlap(statement_terms, token_terms)
    return clamp_score(0.25 + (0.60 * overlap))


def label_similarity_score(
    *,
    label: str | None,
    concept: str,
    field_name: str,
    concept_regex: str,
) -> float:
    target_tokens = _tokenize_text(field_name) | _tokenize_text(
        _local_name(_regex_to_text(concept_regex))
    )
    observed_tokens = _tokenize_text(label or "") | _tokenize_text(_local_name(concept))
    if not target_tokens or not observed_tokens:
        return 0.35
    overlap = _token_overlap(observed_tokens, target_tokens)
    baseline = 0.30 if label else 0.20
    return clamp_score(baseline + (0.70 * overlap))


def calculation_consistency_score(
    *,
    value: object,
    decimals: str | None,
    scale: str | None,
    unit: str | None,
    period_key: str,
    explicit_score: float | None = None,
) -> float:
    if explicit_score is not None:
        return clamp_score(explicit_score)

    numeric_value = parse_numeric(value, parse_scale(scale))
    if numeric_value is None:
        return 0.10

    score = 0.45
    if unit and unit.strip():
        score += 0.20
    if period_key.startswith("instant_") or period_key.startswith("duration_"):
        score += 0.20
    if _is_decimal_hint_valid(decimals):
        score += 0.15
    return clamp_score(score)


def clamp_score(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _regex_match_score(concept: str, pattern: str) -> float:
    try:
        compiled = re.compile(pattern, flags=re.IGNORECASE)
    except re.error:
        return 0.0
    if compiled.fullmatch(concept):
        return 0.90
    if compiled.search(concept):
        return 0.78
    return 0.0


def _tokenize_text(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 1}


def _token_overlap(tokens_a: set[str], tokens_b: set[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    overlap_count = len(tokens_a & tokens_b)
    baseline = min(len(tokens_a), len(tokens_b))
    if baseline == 0:
        return 0.0
    return float(overlap_count) / float(baseline)


def _regex_to_text(pattern: str) -> str:
    return re.sub(r"[^a-z0-9:]+", " ", pattern.lower())


def _local_name(concept: str) -> str:
    if ":" not in concept:
        return concept
    return concept.split(":", maxsplit=1)[1]


def _is_decimal_hint_valid(decimals: str | None) -> bool:
    if decimals is None:
        return False
    token = decimals.strip().lower()
    if token in {"inf", "-inf"}:
        return True
    try:
        int(token)
        return True
    except ValueError:
        return False


def _anchor_source_confidence(anchor_source: str | None) -> float:
    if anchor_source == "issuer_anchor":
        return 0.92
    if anchor_source == "industry_anchor":
        return 0.84
    if anchor_source == "global_anchor":
        return 0.74
    return 0.62


def _mapping_source_confidence_boost(source: str) -> float:
    if source == "issuer_override":
        return 0.08
    if source == "industry_override":
        return 0.04
    if source == "anchor_only":
        return 0.10
    return 0.0
