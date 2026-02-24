from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from statistics import median

from edgar import Company

from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)

_SEC_SEARCH_URL_TEMPLATE = "https://www.sec.gov/edgar/search/#/entityName={ticker}"
_TEXT_MAX_CHARS = 120_000

_FORM_SOURCE_TYPE: dict[str, str] = {
    "10-K": "mda",
    "10-Q": "mda",
    "8-K": "press_release",
}

_SIGNAL_PATTERNS: dict[str, dict[str, tuple[str, ...]]] = {
    "growth_outlook": {
        "up": (
            "raised guidance",
            "increase guidance",
            "strong demand",
            "accelerating growth",
            "record backlog",
            "expect higher revenue",
        ),
        "down": (
            "lowered guidance",
            "decelerating growth",
            "soft demand",
            "declining demand",
            "revenue headwind",
            "expect lower revenue",
        ),
    },
    "margin_outlook": {
        "up": (
            "margin expansion",
            "operating leverage",
            "cost discipline",
            "pricing power",
            "improved margin",
        ),
        "down": (
            "margin pressure",
            "cost inflation",
            "higher input costs",
            "margin compression",
            "weaker margin",
        ),
    },
}

_SOURCE_WEIGHT: dict[str, float] = {"mda": 1.0, "press_release": 0.75}
_SIGNAL_MIN_SCORE = 1.0
_SIGNAL_STALE_WARNING_DAYS = 540
_SIGNAL_STALE_HIGH_RISK_DAYS = 900
_NEGATION_PATTERN = re.compile(
    r"\b(?:no|not|never|without|lack of|did not|does not|can't|cannot|unlikely)\b",
    re.IGNORECASE,
)
_FORWARD_TENSE_PATTERN = re.compile(
    r"\b(?:will|expects?|expecting|guidance|outlook|forecast|project(?:s|ed)?|"
    r"anticipat(?:e|es|ed)|target(?:s|ed)?)\b",
    re.IGNORECASE,
)
_HISTORICAL_TENSE_PATTERN = re.compile(
    r"\b(?:last year|prior year|previous quarter|for the year ended|was|were|had been)\b",
    re.IGNORECASE,
)
_NUMERIC_GUIDANCE_PATTERN = re.compile(
    r"\b(?P<direction>raise(?:d)?|increase(?:d)?|lower(?:ed)?|decrease(?:d)?|"
    r"reduc(?:e|ed)|improv(?:e|ed)|expand(?:ed)?|compress(?:ed)?)"
    r"[^.]{0,80}?\b(?:guidance|outlook|revenue|sales|growth|margin|operating margin)\b"
    r"[^.]{0,40}?\b(?:by|to)\s+(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>%|percent|percentage points?|bps|basis points?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FilingTextRecord:
    form: str
    source_type: str
    text: str
    focus_text: str | None = None
    period: str | None = None
    accession_number: str | None = None
    filing_date: str | None = None
    focus_strategy: str | None = None


@dataclass(frozen=True)
class _MetricSignalAccumulator:
    up_score: float
    down_score: float
    evidence: list[dict[str, object]]
    forward_hit_count: int
    historical_hit_count: int
    numeric_hit_count: int
    numeric_basis_points_samples: list[float]
    filing_age_days_samples: list[int]


@dataclass(frozen=True)
class _PatternHit:
    pattern: str
    start: int
    end: int
    weighted_score: float
    is_forward: bool
    is_historical: bool


def extract_forward_signals_from_sec_text(
    *,
    ticker: str,
    max_filings_per_form: int = 2,
    fetch_records_fn: Callable[[str, int], list[FilingTextRecord]] | None = None,
) -> list[dict[str, object]]:
    fetch_fn = fetch_records_fn or _fetch_recent_filing_text_records
    records = fetch_fn(ticker, max_filings_per_form)
    if not records:
        return []

    grouped = _group_records_for_signals(ticker=ticker, records=records)
    focus_diag = _summarize_focus_usage(records)
    signals: list[dict[str, object]] = []
    for source_type, metrics in grouped.items():
        for metric, acc in metrics.items():
            score = acc.up_score - acc.down_score
            if abs(score) < _SIGNAL_MIN_SCORE:
                continue
            direction = "up" if score > 0 else "down"
            lexical_value_basis_points = abs(score) * 35.0
            numeric_anchor_basis_points = (
                median(acc.numeric_basis_points_samples)
                if acc.numeric_basis_points_samples
                else 0.0
            )
            value_basis_points = _clamp(
                max(lexical_value_basis_points, numeric_anchor_basis_points * 0.75),
                25.0,
                220.0,
            )
            total_context_hits = acc.forward_hit_count + acc.historical_hit_count
            forward_ratio = (
                acc.forward_hit_count / total_context_hits
                if total_context_hits > 0
                else 0.0
            )
            historical_ratio = (
                acc.historical_hit_count / total_context_hits
                if total_context_hits > 0
                else 0.0
            )
            numeric_bonus = min(acc.numeric_hit_count, 2) * 0.04
            median_filing_age_days = (
                int(median(acc.filing_age_days_samples))
                if acc.filing_age_days_samples
                else None
            )
            staleness_penalty = _staleness_confidence_penalty(median_filing_age_days)
            confidence = _clamp(
                0.54
                + min(abs(score), 7.0) * 0.024
                + (forward_ratio * 0.09)
                + numeric_bonus
                - (historical_ratio * 0.06)
                - staleness_penalty,
                0.52,
                0.86,
            )
            evidence = acc.evidence[:3]
            if not evidence:
                continue
            signal_id = (
                f"sec_text_{source_type}_{metric}_"
                f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
            )
            signals.append(
                {
                    "signal_id": signal_id,
                    "source_type": source_type,
                    "metric": metric,
                    "direction": direction,
                    "value": round(value_basis_points, 2),
                    "unit": "basis_points",
                    "confidence": round(confidence, 4),
                    "as_of": datetime.now(UTC).isoformat(),
                    "median_filing_age_days": median_filing_age_days,
                    "evidence": evidence,
                }
            )

    if signals:
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
        log_event(
            logger,
            event="fundamental_forward_signal_text_producer_completed",
            message="forward signal text producer generated signals",
            fields={
                "ticker": ticker,
                "records_total": focus_diag["records_total"],
                "focused_records_total": focus_diag["focused_records_total"],
                "fallback_records_total": focus_diag["fallback_records_total"],
                "focused_form_counts": focus_diag["focused_form_counts"],
                "fallback_form_counts": focus_diag["fallback_form_counts"],
                "signal_count": len(signals),
                "source_types": sorted(
                    {str(item.get("source_type")) for item in signals}
                ),
                "metrics": sorted({str(item.get("metric")) for item in signals}),
                "emitted_doc_types": emitted_doc_types,
                "emitted_focused_doc_types": emitted_focused_doc_types,
                "focused_signals_count": focused_signals_count,
            },
        )
    else:
        log_event(
            logger,
            event="fundamental_forward_signal_text_producer_no_signal",
            message="forward signal text producer found no eligible signals",
            fields={
                "ticker": ticker,
                "records_total": focus_diag["records_total"],
                "focused_records_total": focus_diag["focused_records_total"],
                "fallback_records_total": focus_diag["fallback_records_total"],
                "focused_form_counts": focus_diag["focused_form_counts"],
                "fallback_form_counts": focus_diag["fallback_form_counts"],
            },
        )
    return signals


def _fetch_recent_filing_text_records(
    ticker: str,
    max_filings_per_form: int,
) -> list[FilingTextRecord]:
    company = Company(ticker)
    current_year = date.today().year
    years = [current_year - offset for offset in range(3)]

    records: list[FilingTextRecord] = []
    for form, source_type in _FORM_SOURCE_TYPE.items():
        try:
            filings = company.get_filings(
                form=form,
                year=years,
                amendments=False,
                trigger_full_load=False,
            )
            if filings is None:
                continue
            subset = filings.head(max_filings_per_form)
        except Exception as exc:
            log_event(
                logger,
                event="fundamental_forward_signal_text_form_failed",
                message="failed to fetch sec text filings for form",
                fields={
                    "ticker": ticker,
                    "form": form,
                    "exception": str(exc),
                },
            )
            continue
        for idx in range(max_filings_per_form):
            filing = _safe_get_filing(subset, idx)
            if filing is None:
                break
            text = _safe_get_filing_text(filing)
            if not text:
                continue
            focus_text, focus_strategy = _extract_focus_text_with_strategy_from_filing(
                form=form, filing=filing
            )
            if focus_text is None:
                focus_text = _extract_focus_text(form=form, text=text)
                if focus_text is not None:
                    focus_strategy = "regex_marker"
            records.append(
                FilingTextRecord(
                    form=form,
                    source_type=source_type,
                    text=text,
                    focus_text=focus_text,
                    period=_normalize_text(getattr(filing, "period_of_report", None)),
                    accession_number=_normalize_text(
                        getattr(filing, "accession_number", None)
                    ),
                    filing_date=_normalize_text(getattr(filing, "filing_date", None)),
                    focus_strategy=focus_strategy,
                )
            )
    return records


def _group_records_for_signals(
    *,
    ticker: str,
    records: list[FilingTextRecord],
) -> dict[str, dict[str, _MetricSignalAccumulator]]:
    grouped: dict[str, dict[str, _MetricSignalAccumulator]] = {}
    for record in records:
        focused_section = record.focus_text or _extract_focus_text(
            form=record.form, text=record.text
        )
        analysis_text = focused_section or record.text
        doc_type = _build_doc_type(record.form, used_focus=focused_section is not None)
        for metric, patterns in _SIGNAL_PATTERNS.items():
            up_hits = _find_pattern_hits(analysis_text, patterns["up"])
            down_hits = _find_pattern_hits(analysis_text, patterns["down"])
            numeric_hits = _find_numeric_guidance_hits(
                analysis_text=analysis_text,
                metric=metric,
            )
            if not up_hits and not down_hits and not numeric_hits:
                continue

            source_bucket = grouped.setdefault(record.source_type, {})
            existing = source_bucket.get(metric)
            if existing is None:
                existing = _MetricSignalAccumulator(
                    up_score=0.0,
                    down_score=0.0,
                    evidence=[],
                    forward_hit_count=0,
                    historical_hit_count=0,
                    numeric_hit_count=0,
                    numeric_basis_points_samples=[],
                    filing_age_days_samples=[],
                )

            weight = _SOURCE_WEIGHT.get(record.source_type, 1.0)
            up_score = existing.up_score + (
                sum(hit.weighted_score for hit in up_hits) * weight
            )
            down_score = existing.down_score + (
                sum(hit.weighted_score for hit in down_hits) * weight
            )
            evidence = list(existing.evidence)
            forward_hit_count = existing.forward_hit_count
            historical_hit_count = existing.historical_hit_count
            numeric_hit_count = existing.numeric_hit_count
            numeric_basis_points_samples = list(existing.numeric_basis_points_samples)
            filing_age_days_samples = list(existing.filing_age_days_samples)
            filing_age_days = _filing_age_days(record.filing_date)
            if filing_age_days is not None:
                filing_age_days_samples.append(filing_age_days)

            for hit in up_hits + down_hits:
                if hit.is_forward:
                    forward_hit_count += 1
                if hit.is_historical:
                    historical_hit_count += 1
                snippet = _extract_snippet(analysis_text, hit.start, hit.end)
                if not snippet:
                    continue
                evidence.append(
                    {
                        "text_snippet": snippet,
                        "source_url": _SEC_SEARCH_URL_TEMPLATE.format(ticker=ticker),
                        "doc_type": doc_type,
                        "period": record.period or "N/A",
                        "filing_date": record.filing_date,
                        "accession_number": record.accession_number,
                        "focus_strategy": record.focus_strategy,
                        "rule": "lexical_pattern",
                    }
                )
                if len(evidence) >= 5:
                    break
            if len(evidence) < 5:
                for numeric_hit in numeric_hits:
                    numeric_hit_count += 1
                    numeric_basis_points_samples.append(numeric_hit.value_basis_points)
                    if numeric_hit.direction == "up":
                        up_score += numeric_hit.score * weight
                    else:
                        down_score += numeric_hit.score * weight
                    snippet = _extract_snippet(
                        analysis_text, numeric_hit.start, numeric_hit.end
                    )
                    if not snippet:
                        continue
                    evidence.append(
                        {
                            "text_snippet": snippet,
                            "source_url": _SEC_SEARCH_URL_TEMPLATE.format(
                                ticker=ticker
                            ),
                            "doc_type": doc_type,
                            "period": record.period or "N/A",
                            "filing_date": record.filing_date,
                            "accession_number": record.accession_number,
                            "focus_strategy": record.focus_strategy,
                            "rule": "numeric_guidance",
                            "value_basis_points": round(
                                numeric_hit.value_basis_points, 2
                            ),
                        }
                    )
                    if len(evidence) >= 5:
                        break

            source_bucket[metric] = _MetricSignalAccumulator(
                up_score=up_score,
                down_score=down_score,
                evidence=evidence,
                forward_hit_count=forward_hit_count,
                historical_hit_count=historical_hit_count,
                numeric_hit_count=numeric_hit_count,
                numeric_basis_points_samples=numeric_basis_points_samples,
                filing_age_days_samples=filing_age_days_samples,
            )
    return grouped


def _summarize_focus_usage(records: list[FilingTextRecord]) -> dict[str, object]:
    focused_form_counter: Counter[str] = Counter()
    fallback_form_counter: Counter[str] = Counter()
    for record in records:
        if _record_used_focus(record):
            focused_form_counter[record.form] += 1
        else:
            fallback_form_counter[record.form] += 1
    focused_records_total = sum(focused_form_counter.values())
    fallback_records_total = sum(fallback_form_counter.values())
    return {
        "records_total": len(records),
        "focused_records_total": focused_records_total,
        "fallback_records_total": fallback_records_total,
        "focused_form_counts": dict(focused_form_counter),
        "fallback_form_counts": dict(fallback_form_counter),
    }


def _record_used_focus(record: FilingTextRecord) -> bool:
    if isinstance(record.focus_text, str) and record.focus_text:
        return True
    inferred_focus = _extract_focus_text(form=record.form, text=record.text)
    return isinstance(inferred_focus, str) and bool(inferred_focus)


def _find_pattern_hits(text: str, patterns: tuple[str, ...]) -> list[_PatternHit]:
    normalized = text.lower()
    hits: list[_PatternHit] = []
    for pattern in patterns:
        compiled = re.compile(rf"\b{re.escape(pattern.lower())}\b")
        match_count = 0
        for match in compiled.finditer(normalized):
            context_left = max(0, match.start() - 70)
            context_right = min(len(normalized), match.end() + 90)
            context = normalized[context_left:context_right]
            if _NEGATION_PATTERN.search(context):
                continue
            is_forward = _FORWARD_TENSE_PATTERN.search(context) is not None
            is_historical = _HISTORICAL_TENSE_PATTERN.search(context) is not None
            weighted_score = 1.0
            if is_forward:
                weighted_score *= 1.2
            if is_historical and not is_forward:
                weighted_score *= 0.7
            hits.append(
                _PatternHit(
                    pattern=pattern,
                    start=match.start(),
                    end=match.end(),
                    weighted_score=weighted_score,
                    is_forward=is_forward,
                    is_historical=is_historical,
                )
            )
            match_count += 1
            if match_count >= 2:
                break
    return hits


@dataclass(frozen=True)
class _NumericGuidanceHit:
    direction: str
    start: int
    end: int
    value_basis_points: float
    score: float


def _find_numeric_guidance_hits(
    *,
    analysis_text: str,
    metric: str,
) -> list[_NumericGuidanceHit]:
    text_lower = analysis_text.lower()
    hits: list[_NumericGuidanceHit] = []
    for match in _NUMERIC_GUIDANCE_PATTERN.finditer(text_lower):
        snippet = text_lower[match.start() : match.end()]
        if metric == "growth_outlook" and not any(
            token in snippet for token in ("revenue", "sales", "growth", "guidance")
        ):
            continue
        if metric == "margin_outlook" and "margin" not in snippet:
            continue
        direction = _normalize_guidance_direction(match.group("direction"))
        value_basis_points = _parse_numeric_guidance_value(
            value_text=match.group("value"),
            unit_text=match.group("unit"),
        )
        if value_basis_points <= 0:
            continue
        score = _clamp(value_basis_points / 85.0, 0.5, 3.5)
        hits.append(
            _NumericGuidanceHit(
                direction=direction,
                start=match.start(),
                end=match.end(),
                value_basis_points=value_basis_points,
                score=score,
            )
        )
    return hits[:3]


def _normalize_guidance_direction(direction_text: str) -> str:
    normalized = direction_text.lower()
    if normalized.startswith(("raise", "increase", "improv", "expand")):
        return "up"
    return "down"


def _parse_numeric_guidance_value(*, value_text: str, unit_text: str) -> float:
    try:
        value = float(value_text)
    except ValueError:
        return 0.0
    unit = unit_text.lower().strip()
    if unit in {"%", "percent", "percentage point", "percentage points"}:
        return value * 100.0
    return value


def _extract_snippet(text: str, start: int, end: int, radius: int = 70) -> str | None:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = " ".join(text[left:right].split())
    if not snippet:
        return None
    if len(snippet) > 220:
        return snippet[:217] + "..."
    return snippet


def _extract_focus_text_with_strategy_from_filing(
    *, form: str, filing: object
) -> tuple[str | None, str | None]:
    filing_obj = _safe_get_filing_obj(filing)
    if filing_obj is None:
        return None, None
    normalized_form = form.strip().upper()
    if normalized_form == "10-K":
        return _extract_10k_focus_from_obj_with_strategy(filing_obj)
    if normalized_form == "10-Q":
        return _extract_10q_focus_from_obj_with_strategy(filing_obj)
    if normalized_form == "8-K":
        return _extract_8k_focus_from_obj_with_strategy(filing_obj)
    return None, None


def _extract_focus_text_from_filing(*, form: str, filing: object) -> str | None:
    focus_text, _focus_strategy = _extract_focus_text_with_strategy_from_filing(
        form=form, filing=filing
    )
    return focus_text


def _safe_get_filing_obj(filing: object) -> object | None:
    try:
        obj_fn = getattr(filing, "obj", None)
        if callable(obj_fn):
            return obj_fn()
    except Exception:
        return None
    return None


def _extract_10k_focus_from_obj_with_strategy(
    filing_obj: object,
) -> tuple[str | None, str | None]:
    candidates = [
        (
            _safe_call_get_item_with_part(filing_obj, "Part II", "Item 7"),
            "edgartools_part_item",
        ),
        (_safe_call_get_item(filing_obj, "Item 7"), "edgartools_item_lookup"),
        (_safe_call_get_item(filing_obj, "7"), "edgartools_item_lookup"),
        (
            _safe_call_get_item_from_sections(
                filing_obj,
                keys=("part_ii_item_7", "item_7"),
            ),
            "edgartools_sections_lookup",
        ),
    ]
    return _pick_valid_focus_text_with_strategy(candidates, min_len=120)


def _extract_10q_focus_from_obj_with_strategy(
    filing_obj: object,
) -> tuple[str | None, str | None]:
    candidates = [
        (
            _safe_call_get_item_with_part(filing_obj, "Part I", "Item 2"),
            "edgartools_part_item",
        ),
        (_safe_call_get_item(filing_obj, "Item 2"), "edgartools_item_lookup"),
        (_safe_call_get_item(filing_obj, "2"), "edgartools_item_lookup"),
        (
            _safe_call_get_item_from_sections(
                filing_obj,
                keys=("part_i_item_2", "item_2"),
            ),
            "edgartools_sections_lookup",
        ),
    ]
    return _pick_valid_focus_text_with_strategy(candidates, min_len=100)


def _extract_8k_focus_from_obj_with_strategy(
    filing_obj: object,
) -> tuple[str | None, str | None]:
    candidates = [
        (_safe_call_get_item(filing_obj, "Item 2.02"), "edgartools_item_lookup"),
        (_safe_call_get_item(filing_obj, "2.02"), "edgartools_item_lookup"),
        (_safe_call_get_item(filing_obj, "Item 7.01"), "edgartools_item_lookup"),
        (_safe_call_get_item(filing_obj, "7.01"), "edgartools_item_lookup"),
        (
            _safe_call_get_item_from_sections(
                filing_obj,
                keys=("item_202", "item_701"),
            ),
            "edgartools_sections_lookup",
        ),
        (_safe_call_press_release_text(filing_obj), "edgartools_press_release"),
    ]
    return _pick_valid_focus_text_with_strategy(candidates, min_len=120)


def _safe_call_get_item_with_part(
    filing_obj: object,
    part: str,
    item: str,
) -> str | None:
    try:
        method = getattr(filing_obj, "get_item_with_part", None)
        if callable(method):
            return _normalize_text(method(part, item))
    except Exception:
        return None
    return None


def _safe_call_get_item(filing_obj: object, key: str) -> str | None:
    try:
        getter = getattr(filing_obj, "__getitem__", None)
        if callable(getter):
            return _normalize_text(getter(key))
    except Exception:
        return None
    return None


def _safe_call_get_item_from_sections(
    filing_obj: object,
    *,
    keys: tuple[str, ...],
) -> str | None:
    try:
        sections = getattr(filing_obj, "sections", None)
        if not isinstance(sections, dict):
            return None
        texts: list[str] = []
        for key in keys:
            section = sections.get(key)
            if section is None:
                continue
            text_fn = getattr(section, "text", None)
            if not callable(text_fn):
                continue
            section_text = _normalize_text(text_fn())
            if section_text:
                texts.append(section_text)
        if not texts:
            return None
        return _normalize_text(" ".join(texts))
    except Exception:
        return None


def _safe_call_press_release_text(filing_obj: object) -> str | None:
    try:
        press_releases = getattr(filing_obj, "press_releases", None)
        if press_releases is None:
            return None
        getter = getattr(press_releases, "__getitem__", None)
        if callable(getter):
            first_release = getter(0)
        else:
            first_release = None
        if first_release is None:
            return None
        text_attr = getattr(first_release, "text", None)
        if isinstance(text_attr, str):
            return _normalize_text(text_attr)
        text_fn = getattr(first_release, "text", None)
        if callable(text_fn):
            return _normalize_text(text_fn())
    except Exception:
        return None
    return None


def _pick_valid_focus_text_with_strategy(
    candidates: list[tuple[str | None, str]],
    *,
    min_len: int,
) -> tuple[str | None, str | None]:
    for candidate, strategy in candidates:
        normalized = _normalize_text(candidate)
        if normalized and len(normalized) >= min_len:
            return normalized[:_TEXT_MAX_CHARS], strategy
    return None, None


def _filing_age_days(filing_date: str | None) -> int | None:
    if not isinstance(filing_date, str) or not filing_date:
        return None
    try:
        filing_day = date.fromisoformat(filing_date[:10])
    except ValueError:
        return None
    delta_days = (date.today() - filing_day).days
    if delta_days < 0:
        return 0
    return delta_days


def _staleness_confidence_penalty(filing_age_days: int | None) -> float:
    if filing_age_days is None:
        return 0.0
    if filing_age_days > _SIGNAL_STALE_HIGH_RISK_DAYS:
        return 0.10
    if filing_age_days > _SIGNAL_STALE_WARNING_DAYS:
        return 0.05
    return 0.0


def _extract_focus_text(*, form: str, text: str) -> str | None:
    normalized_form = form.strip().upper()
    if normalized_form == "10-K":
        return _extract_between_markers(
            text,
            start_patterns=(
                r"item\s+7\s*[\.\-:]*\s*management[’']?s discussion and analysis",
                r"management[’']?s discussion and analysis of financial condition and results of operations",
            ),
            end_patterns=(r"item\s+7a", r"item\s+8"),
            min_len=120,
        )
    if normalized_form == "10-Q":
        return _extract_between_markers(
            text,
            start_patterns=(
                r"item\s+2\s*[\.\-:]*\s*management[’']?s discussion and analysis",
                r"management[’']?s discussion and analysis of financial condition and results of operations",
            ),
            end_patterns=(r"item\s+3", r"item\s+4"),
            min_len=100,
        )
    if normalized_form == "8-K":
        # Prefer earnings-release related sections when present.
        return _extract_between_markers(
            text,
            start_patterns=(r"item\s+2\.02", r"item\s+7\.01"),
            end_patterns=(r"item\s+\d+\.\d+",),
            min_len=120,
        )
    return None


def _extract_between_markers(
    text: str,
    *,
    start_patterns: tuple[str, ...],
    end_patterns: tuple[str, ...],
    min_len: int,
) -> str | None:
    if not text:
        return None

    start_idx: int | None = None
    for pattern in start_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match is None:
            continue
        idx = match.start()
        if start_idx is None or idx < start_idx:
            start_idx = idx

    if start_idx is None:
        return None

    end_idx: int | None = None
    search_from = start_idx + 20
    tail = text[search_from:]
    for pattern in end_patterns:
        match = re.search(pattern, tail, flags=re.IGNORECASE)
        if match is None:
            continue
        idx = search_from + match.start()
        if end_idx is None or idx < end_idx:
            end_idx = idx

    section = text[start_idx:end_idx] if end_idx is not None else text[start_idx:]
    normalized = " ".join(section.split())
    if len(normalized) < min_len:
        return None
    return normalized


def _build_doc_type(form: str, *, used_focus: bool) -> str:
    if used_focus:
        return f"{form}_focused"
    return form


def _safe_get_filing(filings: object, index: int) -> object | None:
    try:
        getter = getattr(filings, "get", None)
        if callable(getter):
            return getter(index)
    except Exception:
        return None
    return None


def _safe_get_filing_text(filing: object) -> str | None:
    try:
        text_fn = getattr(filing, "text", None)
        if callable(text_fn):
            text = text_fn()
            normalized = _normalize_text(text)
            if normalized:
                return normalized[:_TEXT_MAX_CHARS]
        full_text_fn = getattr(filing, "full_text_submission", None)
        if callable(full_text_fn):
            full_text = full_text_fn()
            normalized_full_text = _normalize_text(full_text)
            if normalized_full_text:
                return normalized_full_text[:_TEXT_MAX_CHARS]
    except Exception:
        return None
    return None


def _normalize_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized if normalized else None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
