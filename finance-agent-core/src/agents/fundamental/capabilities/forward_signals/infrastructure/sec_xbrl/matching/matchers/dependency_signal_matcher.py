from __future__ import annotations

import os
import re
import threading

from src.shared.kernel.tools.logger import get_logger, log_event

from .regex_signal_extractor import PatternHit

logger = get_logger(__name__)

_SPACY_DEP_LOCK = threading.Lock()
_SPACY_DEP_NLP: object | None = None
_SPACY_DEP_INIT_FAILED = False

_NEGATION_PATTERN = re.compile(
    r"\b(?:no|not|never|without|lack of|did not|does not|can't|cannot|unlikely)\b",
    re.IGNORECASE,
)
_HISTORICAL_TENSE_PATTERN = re.compile(
    r"\b(?:last year|prior year|previous quarter|for the year ended|was|were|had been)\b",
    re.IGNORECASE,
)

_FORWARD_CUE_LEMMAS: set[str] = {
    "expect",
    "project",
    "anticipate",
    "forecast",
    "guide",
    "target",
    "outlook",
    "guidance",
}

_METRIC_LEMMAS: dict[str, set[str]] = {
    "growth_outlook": {"revenue", "sale", "sales", "growth", "demand", "booking"},
    "margin_outlook": {"margin", "profitability", "gross", "operating"},
}

_DIRECTION_LEMMAS: dict[str, dict[str, set[str]]] = {
    "growth_outlook": {
        "up": {"increase", "raise", "accelerate", "improve", "higher", "strong"},
        "down": {"decrease", "lower", "decline", "slow", "soft", "headwind"},
    },
    "margin_outlook": {
        "up": {"expand", "improve", "increase", "higher", "leverage"},
        "down": {"compress", "contract", "decline", "pressure", "inflation", "cost"},
    },
}


def find_metric_dependency_hits(
    *,
    text: str,
    metric: str,
) -> tuple[list[PatternHit], list[PatternHit]]:
    metric_lemmas = _METRIC_LEMMAS.get(metric)
    direction_lemmas = _DIRECTION_LEMMAS.get(metric)
    if metric_lemmas is None or direction_lemmas is None:
        return [], []
    nlp = _get_dependency_nlp()
    if nlp is None:
        return [], []
    try:
        doc = nlp(text)
    except Exception:
        return [], []
    up_hits = _extract_direction_hits(
        text=text,
        doc=doc,
        metric=metric,
        metric_lemmas=metric_lemmas,
        direction="up",
        direction_lemmas=direction_lemmas["up"],
    )
    down_hits = _extract_direction_hits(
        text=text,
        doc=doc,
        metric=metric,
        metric_lemmas=metric_lemmas,
        direction="down",
        direction_lemmas=direction_lemmas["down"],
    )
    return up_hits, down_hits


def _extract_direction_hits(
    *,
    text: str,
    doc: object,
    metric: str,
    metric_lemmas: set[str],
    direction: str,
    direction_lemmas: set[str],
) -> list[PatternHit]:
    hits: list[PatternHit] = []
    for token in doc:
        cue_lemma = _norm_lemma(getattr(token, "lemma_", ""))
        if cue_lemma not in _FORWARD_CUE_LEMMAS:
            continue
        neighborhood = _dependency_neighborhood(token)
        metric_tokens = [
            item
            for item in neighborhood
            if _norm_lemma(getattr(item, "lemma_", "")) in metric_lemmas
        ]
        direction_tokens = [
            item
            for item in neighborhood
            if _norm_lemma(getattr(item, "lemma_", "")) in direction_lemmas
        ]
        if not metric_tokens or not direction_tokens:
            continue
        selected_tokens = [token, metric_tokens[0], direction_tokens[0]]
        start = min(int(getattr(item, "idx", 0)) for item in selected_tokens)
        end = max(
            int(getattr(item, "idx", 0)) + len(str(item)) for item in selected_tokens
        )
        context_left = max(0, start - 70)
        context_right = min(len(text), end + 90)
        context = text[context_left:context_right].lower()
        if _NEGATION_PATTERN.search(context):
            continue
        is_historical = _HISTORICAL_TENSE_PATTERN.search(context) is not None
        weighted_score = 1.12
        if is_historical:
            weighted_score *= 0.8
        hits.append(
            PatternHit(
                pattern=f"dependency_{metric}_{direction}",
                start=start,
                end=end,
                weighted_score=weighted_score,
                is_forward=True,
                is_historical=is_historical,
                rule="dependency_pattern",
            )
        )
        if len(hits) >= 3:
            break
    return _dedupe_hits(hits)


def _dependency_neighborhood(token: object) -> list[object]:
    collected: list[object] = [token]
    seen = {id(token)}
    children = list(getattr(token, "children", []))
    for child in children:
        token_id = id(child)
        if token_id in seen:
            continue
        seen.add(token_id)
        collected.append(child)
    for ancestor in getattr(token, "ancestors", []):
        token_id = id(ancestor)
        if token_id in seen:
            continue
        seen.add(token_id)
        collected.append(ancestor)
    for item in list(collected):
        for child in getattr(item, "children", []):
            token_id = id(child)
            if token_id in seen:
                continue
            seen.add(token_id)
            collected.append(child)
    return collected


def _dedupe_hits(hits: list[PatternHit]) -> list[PatternHit]:
    deduped: dict[tuple[int, int], PatternHit] = {}
    for hit in hits:
        key = (hit.start // 12, hit.end // 12)
        current = deduped.get(key)
        if current is None or hit.weighted_score > current.weighted_score:
            deduped[key] = hit
    return list(deduped.values())


def _norm_lemma(raw: str) -> str:
    return raw.lower().strip()


def _dependency_model_candidates() -> tuple[str, ...]:
    configured = os.getenv("SEC_TEXT_DEPENDENCY_MODEL")
    if configured:
        return (configured, "en_core_web_sm")
    return ("en_core_web_sm",)


def warmup_dependency_matcher() -> dict[str, object]:
    nlp = _get_dependency_nlp()
    if nlp is None:
        return {
            "loaded": False,
            "model": None,
            "error": "dependency model unavailable",
        }
    meta = getattr(nlp, "meta", {})
    model_name = None
    if isinstance(meta, dict):
        raw_name = meta.get("name")
        if isinstance(raw_name, str) and raw_name.strip():
            model_name = raw_name.strip()
    if not model_name:
        model_name = str(getattr(nlp, "lang", "unknown")).strip() or "unknown"
    return {
        "loaded": True,
        "model": model_name,
        "error": None,
    }


def _get_dependency_nlp() -> object | None:
    global _SPACY_DEP_NLP, _SPACY_DEP_INIT_FAILED
    if _SPACY_DEP_INIT_FAILED:
        return None
    if _SPACY_DEP_NLP is not None:
        return _SPACY_DEP_NLP
    with _SPACY_DEP_LOCK:
        if _SPACY_DEP_NLP is not None:
            return _SPACY_DEP_NLP
        if _SPACY_DEP_INIT_FAILED:
            return None
        try:
            import spacy

            for model_name in _dependency_model_candidates():
                try:
                    nlp = spacy.load(
                        model_name,
                        disable=["ner", "textcat"],
                    )
                except Exception:
                    continue
                if not bool(getattr(nlp, "has_pipe", lambda _name: False)("parser")):
                    continue
                _SPACY_DEP_NLP = nlp
                return _SPACY_DEP_NLP
        except Exception as exc:
            _SPACY_DEP_INIT_FAILED = True
            log_event(
                logger,
                event="fundamental_dependency_matcher_spacy_unavailable",
                message="spaCy dependency matcher unavailable; dependency layer is skipped",
                fields={"exception": str(exc)},
            )
            return None
        _SPACY_DEP_INIT_FAILED = True
        log_event(
            logger,
            event="fundamental_dependency_matcher_model_missing",
            message="spaCy dependency model missing; dependency layer is skipped",
            fields={"model_candidates": list(_dependency_model_candidates())},
        )
        return None
