from __future__ import annotations

from collections.abc import Mapping

from src.shared.kernel.types import JSONObject

from .valuation_distribution_preview_service import extract_distribution_summary


def build_monte_carlo_completion_fields(
    calculation_metrics: Mapping[str, object],
) -> dict[str, object]:
    fields: dict[str, object] = {
        "sampler_type": "disabled",
        "executed_iterations": 0,
        "corr_diagnostics_available": False,
        "psd_repaired": False,
    }

    distribution_summary = extract_distribution_summary(dict(calculation_metrics))
    if distribution_summary is None:
        return fields

    diagnostics = distribution_summary.get("diagnostics")
    if not isinstance(diagnostics, Mapping):
        return fields

    sampler_type = diagnostics.get("sampler_type")
    if isinstance(sampler_type, str) and sampler_type:
        fields["sampler_type"] = sampler_type

    executed_iterations = _coerce_non_negative_int(
        diagnostics.get("executed_iterations")
    )
    if executed_iterations is not None:
        fields["executed_iterations"] = executed_iterations

    corr_diagnostics = _coerce_bool(diagnostics.get("corr_diagnostics_available"))
    if corr_diagnostics is not None:
        fields["corr_diagnostics_available"] = corr_diagnostics

    psd_repaired = _coerce_bool(diagnostics.get("psd_repaired"))
    if psd_repaired is not None:
        fields["psd_repaired"] = psd_repaired

    return fields


def build_forward_signal_completion_fields(
    *,
    forward_signals: list[JSONObject] | None,
    build_metadata: Mapping[str, object] | None,
) -> dict[str, object]:
    raw_count = len(forward_signals or [])
    count = raw_count
    source_types: list[str] = []

    if isinstance(build_metadata, Mapping):
        forward_signal_raw = build_metadata.get("forward_signal")
        if isinstance(forward_signal_raw, Mapping):
            parsed_count = _coerce_non_negative_int(
                forward_signal_raw.get("signals_total")
            )
            if parsed_count is not None:
                count = parsed_count
            parsed_sources = _normalize_source_types(
                forward_signal_raw.get("source_types")
            )
            if parsed_sources:
                source_types = parsed_sources

    if not source_types and isinstance(forward_signals, list):
        source_types = _normalize_source_types(
            [
                item.get("source_type")
                for item in forward_signals
                if isinstance(item, Mapping)
            ]
        )

    source_label = ",".join(source_types) if source_types else "none"
    present = raw_count > 0 or count > 0
    return {
        "forward_signals_present": present,
        "forward_signals_count": count,
        "forward_signals_source": source_label,
    }


def _normalize_source_types(raw: object) -> list[str]:
    if not isinstance(raw, list | tuple):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return bool(value)
    return None


def _coerce_non_negative_int(value: object) -> int | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        parsed = int(value)
        return parsed if parsed >= 0 else 0
    return None
