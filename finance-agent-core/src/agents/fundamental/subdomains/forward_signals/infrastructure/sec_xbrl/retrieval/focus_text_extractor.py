from __future__ import annotations

import re

from .pipeline_text_normalization_service import _normalize_text

_TEXT_MAX_CHARS = 120_000


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
        (_safe_call_get_item(filing_obj, "Item 8.01"), "edgartools_item_lookup"),
        (_safe_call_get_item(filing_obj, "8.01"), "edgartools_item_lookup"),
        (_safe_call_get_item(filing_obj, "Item 7.01"), "edgartools_item_lookup"),
        (_safe_call_get_item(filing_obj, "7.01"), "edgartools_item_lookup"),
        (
            _safe_call_get_item_from_sections(
                filing_obj,
                keys=("item_202", "item_801", "item_701"),
            ),
            "edgartools_sections_lookup",
        ),
        (_safe_call_exhibit_99_text(filing_obj), "edgartools_exhibit_99"),
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


def _safe_call_exhibit_99_text(filing_obj: object) -> str | None:
    try:
        sections = getattr(filing_obj, "sections", None)
        if isinstance(sections, dict):
            for key, section in sections.items():
                key_text = str(key).lower()
                if "99" not in key_text:
                    continue
                if "exhibit" not in key_text and "ex99" not in key_text:
                    continue
                text_fn = getattr(section, "text", None)
                if callable(text_fn):
                    section_text = _normalize_text(text_fn())
                    if section_text:
                        return section_text
        exhibits = getattr(filing_obj, "exhibits", None)
        if isinstance(exhibits, dict):
            for key, exhibit in exhibits.items():
                key_text = str(key).lower()
                if not key_text.startswith("99"):
                    continue
                text_attr = getattr(exhibit, "text", None)
                if isinstance(text_attr, str):
                    normalized = _normalize_text(text_attr)
                    if normalized:
                        return normalized
                text_fn = getattr(exhibit, "text", None)
                if callable(text_fn):
                    normalized_fn_text = _normalize_text(text_fn())
                    if normalized_fn_text:
                        return normalized_fn_text
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
        return _extract_between_markers(
            text,
            start_patterns=(
                r"item\s+2\.02",
                r"item\s+8\.01",
                r"item\s+7\.01",
                r"exhibit\s+99(?:\.\d+)?",
            ),
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
