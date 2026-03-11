from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from src.shared.kernel.types import JSONObject

from .contracts import BacktestCase, BaselineCase


def load_backtest_cases(path: Path) -> list[BacktestCase]:
    payload = read_backtest_json_object(path, context="backtest dataset")
    raw_cases = coerce_sequence(payload.get("cases"), "backtest dataset.cases")

    cases: list[BacktestCase] = []
    for index, item in enumerate(raw_cases):
        context = f"backtest dataset.cases[{index}]"
        mapping = coerce_mapping(item, context)
        case_id = coerce_non_empty_string(mapping.get("id"), f"{context}.id")
        model = coerce_non_empty_string(mapping.get("model"), f"{context}.model")
        params = coerce_json_object(mapping.get("params"), f"{context}.params")

        required_metrics_raw = mapping.get("required_metrics")
        required_metrics: tuple[str, ...] = ()
        if required_metrics_raw is not None:
            required_metrics = tuple(
                coerce_non_empty_string(value, f"{context}.required_metrics[{idx}]")
                for idx, value in enumerate(
                    coerce_sequence(required_metrics_raw, f"{context}.required_metrics")
                )
            )
        consensus_target_price_median = coerce_optional_number(
            mapping.get("consensus_target_price_median"),
            f"{context}.consensus_target_price_median",
        )
        target_consensus_quality_bucket = coerce_optional_non_empty_string(
            mapping.get("target_consensus_quality_bucket"),
            f"{context}.target_consensus_quality_bucket",
        )
        target_consensus_confidence_weight = coerce_optional_number(
            mapping.get("target_consensus_confidence_weight"),
            f"{context}.target_consensus_confidence_weight",
        )
        target_consensus_warning_codes_raw = mapping.get(
            "target_consensus_warning_codes"
        )
        target_consensus_warning_codes: tuple[str, ...] = ()
        if target_consensus_warning_codes_raw is not None:
            target_consensus_warning_codes = tuple(
                coerce_non_empty_string(
                    value,
                    f"{context}.target_consensus_warning_codes[{idx}]",
                )
                for idx, value in enumerate(
                    coerce_sequence(
                        target_consensus_warning_codes_raw,
                        f"{context}.target_consensus_warning_codes",
                    )
                )
            )

        cases.append(
            BacktestCase(
                case_id=case_id,
                model=model,
                params=params,
                required_metrics=required_metrics,
                consensus_target_price_median=consensus_target_price_median,
                target_consensus_quality_bucket=target_consensus_quality_bucket,
                target_consensus_confidence_weight=target_consensus_confidence_weight,
                target_consensus_warning_codes=target_consensus_warning_codes,
            )
        )
    return cases


def load_backtest_baseline(path: Path) -> dict[str, BaselineCase]:
    payload = read_backtest_json_object(path, context="backtest baseline")
    raw_cases = coerce_mapping(payload.get("cases"), "backtest baseline.cases")

    baseline: dict[str, BaselineCase] = {}
    for case_id, raw_case in raw_cases.items():
        context = f"backtest baseline.cases.{case_id}"
        mapping = coerce_mapping(raw_case, context)
        model = coerce_non_empty_string(mapping.get("model"), f"{context}.model")
        metrics = coerce_json_object(mapping.get("metrics"), f"{context}.metrics")
        baseline[case_id] = BaselineCase(model=model, metrics=metrics)
    return baseline


def read_backtest_json_object(path: Path, *, context: str) -> JSONObject:
    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    return coerce_json_object(parsed, context)


def coerce_mapping(value: object, context: str) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    raise TypeError(f"{context} must be an object")


def coerce_json_object(value: object, context: str) -> JSONObject:
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"{context} must be a JSON object")


def coerce_sequence(value: object, context: str) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return value
    raise TypeError(f"{context} must be an array")


def coerce_non_empty_string(value: object, context: str) -> str:
    if isinstance(value, str) and value:
        return value
    raise TypeError(f"{context} must be a non-empty string")


def coerce_optional_number(value: object, context: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"{context} must be numeric")
    if isinstance(value, int | float):
        return float(value)
    raise TypeError(f"{context} must be numeric")


def coerce_optional_non_empty_string(value: object, context: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise TypeError(f"{context} must be a non-empty string")
