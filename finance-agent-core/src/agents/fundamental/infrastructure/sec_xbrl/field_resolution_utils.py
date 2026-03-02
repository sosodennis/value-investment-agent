from __future__ import annotations

import re

from .extractor import SearchConfig


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
            )
        )
    return relaxed


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
