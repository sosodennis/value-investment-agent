from __future__ import annotations

from collections.abc import Mapping

from .forward_signal_contracts import (
    SUPPORTED_FORWARD_SIGNAL_DIRECTIONS,
    SUPPORTED_FORWARD_SIGNAL_METRICS,
    SUPPORTED_FORWARD_SIGNAL_SOURCES,
    SUPPORTED_FORWARD_SIGNAL_UNITS,
    ForwardSignal,
    ForwardSignalEvidence,
    ForwardSignalSourceLocator,
)


def parse_forward_signals(raw: object) -> tuple[ForwardSignal, ...]:
    if not isinstance(raw, list | tuple):
        return ()

    parsed: list[ForwardSignal] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            continue
        signal = _parse_forward_signal(item, index=index)
        if signal is not None:
            parsed.append(signal)
    return tuple(parsed)


def _parse_forward_signal(
    raw: Mapping[str, object], *, index: int
) -> ForwardSignal | None:
    signal_id_raw = raw.get("signal_id")
    signal_id = (
        signal_id_raw
        if isinstance(signal_id_raw, str) and signal_id_raw
        else f"signal_{index + 1}"
    )

    source_type = _normalize_text(raw.get("source_type"))
    metric = _normalize_text(raw.get("metric"))
    direction = _normalize_text(raw.get("direction"))
    unit = _normalize_text(raw.get("unit"), default="basis_points")
    confidence = _to_float(raw.get("confidence"))
    value = _to_float(raw.get("value"))

    if source_type not in SUPPORTED_FORWARD_SIGNAL_SOURCES:
        return None
    if metric not in SUPPORTED_FORWARD_SIGNAL_METRICS:
        return None
    if direction not in SUPPORTED_FORWARD_SIGNAL_DIRECTIONS:
        return None
    if unit not in SUPPORTED_FORWARD_SIGNAL_UNITS:
        return None
    if confidence is None or value is None:
        return None

    as_of_raw = raw.get("as_of")
    as_of = as_of_raw if isinstance(as_of_raw, str) and as_of_raw else None
    evidence_raw = raw.get("evidence")
    evidence = _parse_forward_signal_evidence(evidence_raw)
    return ForwardSignal(
        signal_id=signal_id,
        source_type=source_type,
        metric=metric,
        direction=direction,
        value=value,
        unit=unit,
        confidence=confidence,
        as_of=as_of,
        evidence=evidence,
    )


def _parse_forward_signal_evidence(raw: object) -> tuple[ForwardSignalEvidence, ...]:
    if not isinstance(raw, list | tuple):
        return ()
    items: list[ForwardSignalEvidence] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        preview_raw = item.get("preview_text")
        full_text_raw = item.get("full_text")
        source_url_raw = item.get("source_url")
        if not isinstance(preview_raw, str) or not preview_raw.strip():
            continue
        if not isinstance(full_text_raw, str) or not full_text_raw.strip():
            continue
        if not isinstance(source_url_raw, str) or not source_url_raw.strip():
            continue
        doc_type_raw = item.get("doc_type")
        period_raw = item.get("period")
        filing_date_raw = item.get("filing_date")
        accession_number_raw = item.get("accession_number")
        focus_strategy_raw = item.get("focus_strategy")
        extraction_rule_raw = item.get("rule")
        doc_type = (
            doc_type_raw if isinstance(doc_type_raw, str) and doc_type_raw else None
        )
        period = period_raw if isinstance(period_raw, str) and period_raw else None
        filing_date = (
            filing_date_raw
            if isinstance(filing_date_raw, str) and filing_date_raw
            else None
        )
        accession_number = (
            accession_number_raw
            if isinstance(accession_number_raw, str) and accession_number_raw
            else None
        )
        focus_strategy = (
            focus_strategy_raw
            if isinstance(focus_strategy_raw, str) and focus_strategy_raw
            else None
        )
        extraction_rule = (
            extraction_rule_raw
            if isinstance(extraction_rule_raw, str) and extraction_rule_raw
            else None
        )
        source_locator = _parse_forward_signal_source_locator(
            item.get("source_locator")
        )
        items.append(
            ForwardSignalEvidence(
                preview_text=preview_raw.strip(),
                full_text=full_text_raw.strip(),
                source_url=source_url_raw.strip(),
                doc_type=doc_type,
                period=period,
                filing_date=filing_date,
                accession_number=accession_number,
                focus_strategy=focus_strategy,
                extraction_rule=extraction_rule,
                source_locator=source_locator,
            )
        )
    return tuple(items)


def _parse_forward_signal_source_locator(
    raw: object,
) -> ForwardSignalSourceLocator | None:
    if not isinstance(raw, Mapping):
        return None
    text_scope_raw = raw.get("text_scope")
    char_start_raw = raw.get("char_start")
    char_end_raw = raw.get("char_end")
    if text_scope_raw != "metric_text":
        return None
    if not isinstance(char_start_raw, int) or char_start_raw < 0:
        return None
    if not isinstance(char_end_raw, int) or char_end_raw <= 0:
        return None
    if char_end_raw < char_start_raw:
        return None
    return ForwardSignalSourceLocator(
        text_scope=text_scope_raw,
        char_start=char_start_raw,
        char_end=char_end_raw,
    )


def _normalize_text(value: object, *, default: str | None = None) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized:
            return normalized
    return default or ""


def _to_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
