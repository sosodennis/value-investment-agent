from __future__ import annotations

from collections.abc import Callable, Mapping


def _build_signal_emission_fields(
    signals: list[dict[str, object]],
) -> dict[str, object]:
    emitted_doc_types = sorted(
        {
            str(evidence.get("doc_type"))
            for signal in signals
            for evidence in signal.get("evidence", [])
            if isinstance(evidence, dict)
            and isinstance(evidence.get("doc_type"), str)
            and evidence.get("doc_type")
        }
    )
    emitted_focused_doc_types = sorted(
        {
            doc_type
            for doc_type in emitted_doc_types
            if isinstance(doc_type, str) and doc_type.endswith("_focused")
        }
    )
    focused_signals_count = sum(
        1
        for signal in signals
        if isinstance(signal.get("evidence"), list)
        and any(
            isinstance(evidence, dict)
            and isinstance(evidence.get("doc_type"), str)
            and evidence.get("doc_type", "").endswith("_focused")
            for evidence in signal.get("evidence", [])
        )
    )
    return {
        "signal_count": len(signals),
        "source_types": sorted({str(item.get("source_type")) for item in signals}),
        "metrics": sorted({str(item.get("metric")) for item in signals}),
        "emitted_doc_types": emitted_doc_types,
        "emitted_focused_doc_types": emitted_focused_doc_types,
        "focused_signals_count": focused_signals_count,
    }


def build_text_signal_log_fields(
    *,
    ticker: str,
    focus_diag: Mapping[str, object],
    pipeline_diag: object,
    finbert_direction_diag: Mapping[str, object],
    debug_retrieval_preview_enabled: bool,
    build_pipeline_diagnostics_fields_fn: Callable[..., dict[str, object]],
    signals: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "ticker": ticker,
        "records_total": focus_diag["records_total"],
        "focused_records_total": focus_diag["focused_records_total"],
        "fallback_records_total": focus_diag["fallback_records_total"],
        "focused_form_counts": focus_diag["focused_form_counts"],
        "fallback_form_counts": focus_diag["fallback_form_counts"],
        **build_pipeline_diagnostics_fields_fn(
            pipeline_diag,
            debug_retrieval_preview_enabled=debug_retrieval_preview_enabled,
        ),
        **dict(finbert_direction_diag),
    }
    if signals:
        fields.update(_build_signal_emission_fields(signals))
    return fields
