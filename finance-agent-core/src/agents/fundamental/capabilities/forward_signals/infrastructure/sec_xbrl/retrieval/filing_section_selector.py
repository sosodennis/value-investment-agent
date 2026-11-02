from __future__ import annotations

import re
from dataclasses import dataclass

_EIGHT_K_FORM = "8-K"
_MIN_SENTENCE_WORDS = 6
_MIN_ALPHA_RATIO = 0.45

_SECTION_PRIORITY: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("item_202", re.compile(r"\bitem\s+2\.02\b", re.IGNORECASE)),
    ("item_801", re.compile(r"\bitem\s+8\.01\b", re.IGNORECASE)),
    ("item_701", re.compile(r"\bitem\s+7\.01\b", re.IGNORECASE)),
    (
        "exhibit_99",
        re.compile(r"\bexhibit\s+99(?:\.\d+)?\b|\bex-?99(?:\.\d+)?\b", re.IGNORECASE),
    ),
)
_SECTION_END_PATTERN = re.compile(r"\bitem\s+\d+\.\d+\b", re.IGNORECASE)

_NOISE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsignatures?\b", re.IGNORECASE),
    re.compile(r"\bindex\b", re.IGNORECASE),
    re.compile(r"\bform\s+8-?k\b", re.IGNORECASE),
    re.compile(
        r"pursuant to the requirements of the securities exchange act",
        re.IGNORECASE,
    ),
    re.compile(r"\bcheck the appropriate box\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class FilingSectionSelectionResult:
    text: str
    sections_selected: int = 0
    noise_sentences_skipped: int = 0


def is_8k_form(form: str) -> bool:
    return form.strip().upper() == _EIGHT_K_FORM


def refine_8k_analysis_text(text: str) -> FilingSectionSelectionResult:
    if not text:
        return FilingSectionSelectionResult(text=text)
    prioritized_text, section_count = _extract_priority_sections(text)
    filtered_text, skipped_count = _filter_noise_sentences(prioritized_text)
    if not filtered_text:
        fallback_text = " ".join(prioritized_text.split())
        return FilingSectionSelectionResult(
            text=fallback_text,
            sections_selected=section_count,
            noise_sentences_skipped=skipped_count,
        )
    return FilingSectionSelectionResult(
        text=filtered_text,
        sections_selected=section_count,
        noise_sentences_skipped=skipped_count,
    )


def _extract_priority_sections(text: str) -> tuple[str, int]:
    segments: list[str] = []
    consumed_ranges: list[tuple[int, int]] = []
    for _label, pattern in _SECTION_PRIORITY:
        for match in pattern.finditer(text):
            start = match.start()
            end = _find_section_end(text, start + 1)
            if _overlaps_existing((start, end), consumed_ranges):
                continue
            segment = " ".join(text[start:end].split())
            if len(segment) < 80:
                continue
            segments.append(segment)
            consumed_ranges.append((start, end))
            break
    if not segments:
        return " ".join(text.split()), 0
    return " ".join(segments), len(segments)


def _find_section_end(text: str, search_from: int) -> int:
    match = _SECTION_END_PATTERN.search(text, pos=search_from)
    if match is None:
        return len(text)
    return match.start()


def _overlaps_existing(
    candidate: tuple[int, int],
    existing: list[tuple[int, int]],
) -> bool:
    candidate_start, candidate_end = candidate
    for start, end in existing:
        if candidate_start < end and candidate_end > start:
            return True
    return False


def _filter_noise_sentences(text: str) -> tuple[str, int]:
    sentences = _split_sentences(text)
    if not sentences:
        return "", 0
    kept: list[str] = []
    skipped = 0
    for sentence in sentences:
        normalized = " ".join(sentence.split())
        if not normalized:
            continue
        if _is_noise_sentence(normalized):
            skipped += 1
            continue
        if _is_low_density_sentence(normalized):
            skipped += 1
            continue
        kept.append(normalized)
    return " ".join(kept), skipped


def _split_sentences(text: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[\.\!\?])\s+", text)
        if sentence and sentence.strip()
    ]


def _is_noise_sentence(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(pattern.search(lowered) for pattern in _NOISE_PATTERNS)


def _is_low_density_sentence(sentence: str) -> bool:
    words = sentence.split()
    if len(words) < _MIN_SENTENCE_WORDS:
        return True
    alpha_chars = sum(1 for char in sentence if char.isalpha())
    ratio = alpha_chars / max(1, len(sentence))
    return ratio < _MIN_ALPHA_RATIO
