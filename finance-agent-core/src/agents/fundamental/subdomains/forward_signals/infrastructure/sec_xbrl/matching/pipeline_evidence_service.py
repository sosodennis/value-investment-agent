from __future__ import annotations

import re

_EVIDENCE_FULL_MAX_CHARS = 1_200
_EVIDENCE_PREVIEW_MAX_CHARS = 220
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _align_left_to_word_boundary(text: str, index: int) -> int:
    bounded = max(0, min(index, len(text)))
    while bounded > 0 and text[bounded - 1].isalnum():
        bounded -= 1
    while bounded < len(text) and text[bounded].isspace():
        bounded += 1
    return bounded


def _align_right_to_word_boundary(text: str, index: int) -> int:
    bounded = max(0, min(index, len(text)))
    while bounded > 0 and text[bounded - 1].isspace():
        bounded -= 1
    while bounded < len(text) and text[bounded].isalnum():
        bounded += 1
    return bounded


def _truncate_at_word_boundary(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    clipped = value[:max_chars].rstrip()
    if not clipped:
        return value[:max_chars]
    boundary = clipped.rfind(" ")
    if boundary >= int(max_chars * 0.6):
        return clipped[:boundary].rstrip()
    return clipped


def _build_sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    sentence_start = 0
    for match in _SENTENCE_BOUNDARY_RE.finditer(text):
        sentence_end = match.start()
        start_idx = sentence_start
        end_idx = sentence_end
        while start_idx < end_idx and text[start_idx].isspace():
            start_idx += 1
        while end_idx > start_idx and text[end_idx - 1].isspace():
            end_idx -= 1
        if end_idx > start_idx:
            spans.append((start_idx, end_idx))
        sentence_start = match.end()

    final_start = sentence_start
    final_end = len(text)
    while final_start < final_end and text[final_start].isspace():
        final_start += 1
    while final_end > final_start and text[final_end - 1].isspace():
        final_end -= 1
    if final_end > final_start:
        spans.append((final_start, final_end))

    return spans


def _find_span_index_for_hit(
    spans: list[tuple[int, int]],
    *,
    start: int,
    end: int,
) -> int | None:
    if not spans:
        return None
    for idx, (span_start, span_end) in enumerate(spans):
        if start < span_end and end > span_start:
            return idx
    for idx, (span_start, _span_end) in enumerate(spans):
        if start <= span_start:
            return idx
    return len(spans) - 1


def _extract_snippet(text: str, start: int, end: int, radius: int = 220) -> str | None:
    text_len = len(text)
    if text_len == 0:
        return None
    bounded_start = max(0, min(start, text_len))
    bounded_end = max(bounded_start, min(end, text_len))
    sentence_spans = _build_sentence_spans(text)
    span_idx = _find_span_index_for_hit(
        sentence_spans,
        start=bounded_start,
        end=bounded_end,
    )

    if span_idx is None:
        left = _align_left_to_word_boundary(text, max(0, bounded_start - radius))
        right = _align_right_to_word_boundary(text, min(text_len, bounded_end + radius))
    else:
        target_left = max(0, bounded_start - radius)
        target_right = min(text_len, bounded_end + radius)
        left_idx = span_idx
        right_idx = span_idx
        while left_idx > 0 and sentence_spans[left_idx][0] > target_left:
            left_idx -= 1
        while (
            right_idx < len(sentence_spans) - 1
            and sentence_spans[right_idx][1] < target_right
        ):
            right_idx += 1
        left = sentence_spans[left_idx][0]
        right = sentence_spans[right_idx][1]

    if right <= left:
        return None
    snippet = " ".join(text[left:right].split())
    if not snippet:
        return None
    return _truncate_at_word_boundary(snippet, _EVIDENCE_FULL_MAX_CHARS)


def _build_evidence_preview(full_text: str) -> str:
    normalized = " ".join(full_text.split())
    if len(normalized) <= _EVIDENCE_PREVIEW_MAX_CHARS:
        return normalized
    return normalized[: _EVIDENCE_PREVIEW_MAX_CHARS - 3].rstrip() + "..."


def _append_unique_evidence(
    evidence: list[dict[str, object]],
    candidate: dict[str, object],
) -> None:
    snippet_raw = candidate.get("full_text")
    if not isinstance(snippet_raw, str) or not snippet_raw:
        return
    if _has_duplicate_evidence(evidence, candidate):
        return
    evidence.append(candidate)


def _has_duplicate_evidence(
    evidence: list[dict[str, object]],
    candidate: dict[str, object],
) -> bool:
    candidate_scope = _evidence_scope(candidate)
    candidate_norm = _normalize_evidence_snippet(candidate.get("full_text"))
    if not candidate_norm:
        return False
    for existing in evidence:
        if _evidence_scope(existing) != candidate_scope:
            continue
        existing_norm = _normalize_evidence_snippet(existing.get("full_text"))
        if not existing_norm:
            continue
        if candidate_norm == existing_norm:
            return True
        if (
            len(candidate_norm) >= 80
            and len(existing_norm) >= 80
            and (candidate_norm in existing_norm or existing_norm in candidate_norm)
        ):
            return True
    return False


def _evidence_scope(
    candidate: dict[str, object],
) -> tuple[str | None, str | None, str | None]:
    accession_raw = candidate.get("accession_number")
    accession = (
        accession_raw if isinstance(accession_raw, str) and accession_raw else None
    )
    source_url_raw = candidate.get("source_url")
    source_url = (
        source_url_raw if isinstance(source_url_raw, str) and source_url_raw else None
    )
    doc_type_raw = candidate.get("doc_type")
    doc_type = doc_type_raw if isinstance(doc_type_raw, str) and doc_type_raw else None
    return accession, source_url, doc_type


def _normalize_evidence_snippet(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.lower()
    lowered = re.sub(r"\s+", " ", lowered)
    normalized = re.sub(r"[^a-z0-9]+", " ", lowered).strip()
    return normalized or None
