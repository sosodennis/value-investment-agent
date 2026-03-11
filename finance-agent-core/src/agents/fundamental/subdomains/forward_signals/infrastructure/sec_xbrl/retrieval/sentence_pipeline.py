from __future__ import annotations

import os
import re
import threading
from collections import deque
from collections.abc import Iterable

from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)

_DEFAULT_CHUNK_SIZE = 3000
_DEFAULT_CHUNK_OVERLAP = 250
_MIN_SENTENCE_LEN = 14
_DEFAULT_MAX_SENTENCE_CHARS = 420
_MIN_SENTENCE_SPLIT_CHARS = 120
_HARD_WRAP_MIN_RATIO = 0.6

_CLAUSE_SPLIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<=[\.;\?\!])\s+"),
    re.compile(r"(?<=:)\s+"),
    re.compile(
        r",\s+(?=(?:and|but|while|which|that|who|because|although|however|whereas)\b)",
        re.IGNORECASE,
    ),
    re.compile(r"\s+-{1,2}\s+"),
)

_SPACY_NLP_LOCK = threading.Lock()
_SPACY_NLP: object | None = None
_SPACY_INIT_FAILED = False


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return max(minimum, parsed)


def split_text_into_sentences(
    text: str,
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    max_sentence_chars: int | None = None,
) -> list[str]:
    if not text:
        return []

    resolved_chunk_size = chunk_size or _env_int(
        "SEC_TEXT_CHUNK_SIZE",
        _DEFAULT_CHUNK_SIZE,
        minimum=300,
    )
    resolved_chunk_overlap = chunk_overlap or _env_int(
        "SEC_TEXT_CHUNK_OVERLAP",
        _DEFAULT_CHUNK_OVERLAP,
        minimum=0,
    )
    resolved_max_sentence_chars = max_sentence_chars or _env_int(
        "SEC_TEXT_MAX_SENTENCE_CHARS",
        _DEFAULT_MAX_SENTENCE_CHARS,
        minimum=_MIN_SENTENCE_SPLIT_CHARS,
    )
    chunks = _recursive_char_chunks(
        text,
        chunk_size=resolved_chunk_size,
        chunk_overlap=resolved_chunk_overlap,
    )
    sentences: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        for sentence in _segment_sentences(chunk):
            normalized = " ".join(sentence.split())
            for bounded in _split_overlong_sentence(
                normalized,
                max_chars=resolved_max_sentence_chars,
            ):
                if len(bounded) < _MIN_SENTENCE_LEN:
                    continue
                dedupe_key = bounded.lower()
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                sentences.append(bounded)
    return sentences


def _split_overlong_sentence(text: str, *, max_chars: int) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]
    pending: deque[str] = deque([normalized])
    resolved: list[str] = []
    while pending:
        current = pending.popleft().strip()
        if not current:
            continue
        if len(current) <= max_chars:
            resolved.append(current)
            continue
        clause_parts = _split_by_clause_boundaries(current)
        if len(clause_parts) <= 1:
            resolved.extend(_hard_wrap_sentence(current, max_chars=max_chars))
            continue
        for part in clause_parts:
            if len(part) <= max_chars:
                resolved.append(part)
            else:
                pending.append(part)
    return [piece for piece in resolved if piece]


def _split_by_clause_boundaries(text: str) -> list[str]:
    for pattern in _CLAUSE_SPLIT_PATTERNS:
        pieces = [piece.strip() for piece in pattern.split(text) if piece.strip()]
        if len(pieces) <= 1:
            continue
        if max(len(piece) for piece in pieces) >= len(text):
            continue
        return pieces
    return [text]


def _hard_wrap_sentence(text: str, *, max_chars: int) -> list[str]:
    current = text.strip()
    if len(current) <= max_chars:
        return [current] if current else []
    pieces: list[str] = []
    while len(current) > max_chars:
        lower_bound = max(1, int(max_chars * _HARD_WRAP_MIN_RATIO))
        split_idx = current.rfind(" ", lower_bound, max_chars + 1)
        if split_idx <= 0:
            split_idx = current.find(" ", max_chars)
        if split_idx <= 0:
            split_idx = max_chars
        head = current[:split_idx].strip()
        if head:
            pieces.append(head)
        current = current[split_idx:].strip()
    if current:
        pieces.append(current)
    return pieces


def _recursive_char_chunks(
    text: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=min(max(0, chunk_overlap), max(0, chunk_size - 1)),
            separators=["\n\n", "\n", ". ", " ", ""],
            keep_separator=True,
        )
        pieces = splitter.split_text(text)
        return pieces if pieces else [text]
    except Exception:
        return _fallback_chunks(
            text, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )


def _fallback_chunks(text: str, *, chunk_size: int, chunk_overlap: int) -> list[str]:
    normalized = " ".join(text.split())
    if len(normalized) <= chunk_size:
        return [normalized]
    step = max(1, chunk_size - min(chunk_overlap, chunk_size - 1))
    parts: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + chunk_size)
        parts.append(normalized[start:end])
        if end >= len(normalized):
            break
        start += step
    return parts


def _segment_sentences(text: str) -> list[str]:
    nlp = _get_spacy_sentencizer()
    if nlp is not None:
        doc = nlp(text)
        sentences = [str(span).strip() for span in getattr(doc, "sents", [])]
        return [s for s in sentences if s]
    return _regex_sentence_split(text)


def _get_spacy_sentencizer() -> object | None:
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
            if "sentencizer" not in nlp.pipe_names:
                nlp.add_pipe("sentencizer")
            _SPACY_NLP = nlp
            return _SPACY_NLP
        except Exception as exc:
            _SPACY_INIT_FAILED = True
            log_event(
                logger,
                event="fundamental_sentence_pipeline_spacy_unavailable",
                message="spaCy sentencizer unavailable; fallback sentence split is active",
                fields={"exception": str(exc)},
            )
            return None


def _regex_sentence_split(text: str) -> list[str]:
    pieces = re.split(r"(?<=[\.\!\?])\s+", text)
    return [piece.strip() for piece in pieces if piece and piece.strip()]


def join_sentences(sentences: Iterable[str]) -> str:
    return " ".join(sentence.strip() for sentence in sentences if sentence.strip())
