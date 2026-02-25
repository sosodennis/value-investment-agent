from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from src.shared.kernel.tools.logger import get_logger, log_event

from .regex_signal_extractor import PatternHit

logger = get_logger(__name__)

_SPACY_NLP_LOCK = threading.Lock()
_SPACY_NLP: object | None = None
_SPACY_INIT_FAILED = False

_NEGATION_PATTERN = re.compile(
    r"\b(?:no|not|never|without|lack of|did not|does not|can't|cannot|unlikely)\b",
    re.IGNORECASE,
)
_HISTORICAL_TENSE_PATTERN = re.compile(
    r"\b(?:last year|prior year|previous quarter|for the year ended|was|were|had been)\b",
    re.IGNORECASE,
)
_WINDOW_LEFT = 8
_WINDOW_RIGHT = 12

_FORWARD_CUE_LEMMAS: set[str] = {
    "expect",
    "project",
    "anticipate",
    "forecast",
    "guide",
    "target",
    "see",
    "outlook",
    "guidance",
}

_METRIC_LEMMAS: dict[str, set[str]] = {
    "growth_outlook": {"revenue", "sale", "sales", "growth", "demand", "bookings"},
    "margin_outlook": {"margin", "profitability", "operating", "gross"},
}

_DIRECTION_LEMMAS: dict[str, dict[str, set[str]]] = {
    "growth_outlook": {
        "up": {"raise", "increase", "accelerate", "improve", "higher", "strong"},
        "down": {"lower", "decrease", "decline", "slow", "soft", "weaker", "headwind"},
    },
    "margin_outlook": {
        "up": {"expand", "improve", "increase", "higher", "leverage"},
        "down": {
            "pressure",
            "compress",
            "contract",
            "decline",
            "weaker",
            "inflation",
            "cost",
        },
    },
}

_IRREGULAR_LEMMA_MAP: dict[str, str] = {
    "expects": "expect",
    "expected": "expect",
    "expecting": "expect",
    "projects": "project",
    "projected": "project",
    "projecting": "project",
    "guides": "guide",
    "guided": "guide",
    "guiding": "guide",
    "raised": "raise",
    "raising": "raise",
    "raises": "raise",
    "increased": "increase",
    "increasing": "increase",
    "improved": "improve",
    "improving": "improve",
    "expanded": "expand",
    "expanding": "expand",
    "compressed": "compress",
    "compressing": "compress",
    "declining": "decline",
    "decreased": "decrease",
    "decreasing": "decrease",
    "margins": "margin",
    "sales": "sale",
    "headwinds": "headwind",
}


@dataclass(frozen=True)
class _TokenView:
    text: str
    lemma: str
    start: int
    end: int


def find_metric_lemma_hits(
    *,
    text: str,
    metric: str,
) -> tuple[list[PatternHit], list[PatternHit]]:
    metric_lemmas = _METRIC_LEMMAS.get(metric)
    direction_lemmas = _DIRECTION_LEMMAS.get(metric)
    if metric_lemmas is None or direction_lemmas is None:
        return [], []

    tokens = _tokenize_text(text)
    if not tokens:
        return [], []

    up_hits = _find_direction_hits(
        text=text,
        tokens=tokens,
        metric=metric,
        direction="up",
        metric_lemmas=metric_lemmas,
        direction_lemmas=direction_lemmas["up"],
    )
    down_hits = _find_direction_hits(
        text=text,
        tokens=tokens,
        metric=metric,
        direction="down",
        metric_lemmas=metric_lemmas,
        direction_lemmas=direction_lemmas["down"],
    )
    return up_hits, down_hits


def _find_direction_hits(
    *,
    text: str,
    tokens: list[_TokenView],
    metric: str,
    direction: str,
    metric_lemmas: set[str],
    direction_lemmas: set[str],
) -> list[PatternHit]:
    hits: list[PatternHit] = []
    for idx, token in enumerate(tokens):
        if token.lemma not in _FORWARD_CUE_LEMMAS:
            continue
        window_start = max(0, idx - _WINDOW_LEFT)
        window_end = min(len(tokens), idx + _WINDOW_RIGHT + 1)
        window = tokens[window_start:window_end]
        metric_tokens = [item for item in window if item.lemma in metric_lemmas]
        direction_tokens = [item for item in window if item.lemma in direction_lemmas]
        if not metric_tokens or not direction_tokens:
            continue
        candidate_tokens = [token, metric_tokens[0], direction_tokens[0]]
        start = min(item.start for item in candidate_tokens)
        end = max(item.end for item in candidate_tokens)
        context_left = max(0, start - 70)
        context_right = min(len(text), end + 90)
        context = text[context_left:context_right].lower()
        if _NEGATION_PATTERN.search(context):
            continue
        is_historical = _HISTORICAL_TENSE_PATTERN.search(context) is not None
        weighted_score = 1.08
        if is_historical:
            weighted_score *= 0.75
        hits.append(
            PatternHit(
                pattern=f"lemma_{metric}_{direction}",
                start=start,
                end=end,
                weighted_score=weighted_score,
                is_forward=True,
                is_historical=is_historical,
                rule="lemma_pattern",
            )
        )
        if len(hits) >= 3:
            break
    return _dedupe_hits(hits)


def _dedupe_hits(hits: list[PatternHit]) -> list[PatternHit]:
    deduped: dict[tuple[int, int], PatternHit] = {}
    for hit in hits:
        key = (hit.start // 12, hit.end // 12)
        current = deduped.get(key)
        if current is None or hit.weighted_score > current.weighted_score:
            deduped[key] = hit
    return list(deduped.values())


def _tokenize_text(text: str) -> list[_TokenView]:
    nlp = _get_spacy_nlp()
    if nlp is not None:
        doc = nlp(text)
        tokens: list[_TokenView] = []
        for token in doc:
            token_text = str(token)
            if not token_text.strip():
                continue
            if not token_text[0].isalnum():
                continue
            start = int(getattr(token, "idx", 0))
            end = start + len(token_text)
            tokens.append(
                _TokenView(
                    text=token_text,
                    lemma=_lemma_like(token_text),
                    start=start,
                    end=end,
                )
            )
        return tokens
    return _fallback_tokenize_text(text)


def _fallback_tokenize_text(text: str) -> list[_TokenView]:
    tokens: list[_TokenView] = []
    for match in re.finditer(r"[A-Za-z][A-Za-z\\-']*", text):
        word = match.group(0)
        tokens.append(
            _TokenView(
                text=word,
                lemma=_lemma_like(word),
                start=match.start(),
                end=match.end(),
            )
        )
    return tokens


def _get_spacy_nlp() -> object | None:
    global _SPACY_NLP, _SPACY_INIT_FAILED
    if _SPACY_INIT_FAILED:
        return None
    if _SPACY_NLP is not None:
        return _SPACY_NLP
    with _SPACY_NLP_LOCK:
        if _SPACY_NLP is not None:
            return _SPACY_NLP
        if _SPACY_INIT_FAILED:
            return None
        try:
            import spacy

            nlp = spacy.blank("en")
            _SPACY_NLP = nlp
            return _SPACY_NLP
        except Exception as exc:
            _SPACY_INIT_FAILED = True
            log_event(
                logger,
                event="fundamental_lemma_matcher_spacy_unavailable",
                message="spaCy tokenizer unavailable; lemma matcher fallback is active",
                fields={"exception": str(exc)},
            )
            return None


def _lemma_like(word: str) -> str:
    normalized = word.lower().strip("'")
    if not normalized:
        return normalized
    mapped = _IRREGULAR_LEMMA_MAP.get(normalized)
    if mapped is not None:
        return mapped
    if len(normalized) > 4 and normalized.endswith("ies"):
        normalized = normalized[:-3] + "y"
    elif len(normalized) > 5 and normalized.endswith("ing"):
        normalized = normalized[:-3]
    elif len(normalized) > 4 and normalized.endswith("ed"):
        normalized = normalized[:-2]
    elif len(normalized) > 4 and normalized.endswith("es"):
        normalized = normalized[:-2]
    elif len(normalized) > 3 and normalized.endswith("s"):
        normalized = normalized[:-1]
    mapped_after = _IRREGULAR_LEMMA_MAP.get(normalized)
    if mapped_after is not None:
        return mapped_after
    return normalized
