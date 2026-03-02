from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict

from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)

_EMBED_MODEL_NAME = os.getenv(
    "SEC_TEXT_EMBED_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
)
_HF_LOCAL_FILES_ONLY = os.getenv("HF_LOCAL_FILES_ONLY", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
_DENSE_CORPUS_CACHE_MAX_ITEMS = 16
_DENSE_QUERY_CACHE_MAX_ITEMS = 64


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


class _DenseRetriever:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._loaded = False
        self._model: object | None = None
        self._load_error: str | None = None
        self._corpus_embeddings_cache: OrderedDict[tuple[int, str], object] = (
            OrderedDict()
        )
        self._query_embedding_cache: OrderedDict[str, object] = OrderedDict()
        self._corpus_cache_max_items = _env_int(
            "SEC_TEXT_DENSE_CORPUS_CACHE_MAX_ITEMS",
            _DENSE_CORPUS_CACHE_MAX_ITEMS,
            minimum=1,
        )
        self._query_cache_max_items = _env_int(
            "SEC_TEXT_DENSE_QUERY_CACHE_MAX_ITEMS",
            _DENSE_QUERY_CACHE_MAX_ITEMS,
            minimum=1,
        )

    def rank(self, query: str, corpus: list[str]) -> list[int]:
        rankings = self.rank_many(queries=[query], corpus=corpus)
        if not rankings:
            return []
        return rankings[0]

    def rank_many(self, *, queries: list[str], corpus: list[str]) -> list[list[int]]:
        if not queries:
            return []
        if not corpus:
            return [[] for _ in queries]
        if not self._ensure_loaded():
            return [[] for _ in queries]
        try:
            import numpy as np

            if self._model is None:
                return [[] for _ in queries]
            embeddings = self._get_or_encode_corpus_embeddings(corpus=corpus)
            if embeddings is None:
                return [[] for _ in queries]
            query_embeddings = self._get_or_encode_query_embeddings(queries=queries)
            if query_embeddings is None:
                return [[] for _ in queries]
            score_matrix = np.dot(embeddings, query_embeddings.T)
            rankings: list[list[int]] = []
            for col in range(score_matrix.shape[1]):
                scores = score_matrix[:, col]
                ranked = sorted(
                    range(len(scores)),
                    key=lambda idx: float(scores[idx]),
                    reverse=True,
                )
                rankings.append(ranked)
            return rankings
        except Exception as exc:
            log_event(
                logger,
                event="fundamental_hybrid_retriever_dense_failed",
                message="dense retriever failed; sparse rank only",
                fields={"exception": str(exc)},
            )
            return [[] for _ in queries]

    def _ensure_loaded(self) -> bool:
        if self._loaded:
            return True
        if self._load_error is not None:
            return False
        with self._lock:
            if self._loaded:
                return True
            if self._load_error is not None:
                return False
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(
                    _EMBED_MODEL_NAME,
                    local_files_only=_HF_LOCAL_FILES_ONLY,
                )
                self._loaded = True
                log_event(
                    logger,
                    event="fundamental_hybrid_retriever_dense_loaded",
                    message="dense retriever model loaded",
                    fields={
                        "model": _EMBED_MODEL_NAME,
                        "local_files_only": _HF_LOCAL_FILES_ONLY,
                    },
                )
                return True
            except Exception as exc:
                self._load_error = str(exc)
                log_event(
                    logger,
                    event="fundamental_hybrid_retriever_dense_unavailable",
                    message="dense retriever unavailable; sparse rank only",
                    fields={
                        "model": _EMBED_MODEL_NAME,
                        "local_files_only": _HF_LOCAL_FILES_ONLY,
                        "exception": self._load_error,
                    },
                )
                return False

    def _get_or_encode_corpus_embeddings(self, *, corpus: list[str]) -> object | None:
        if self._model is None:
            return None
        key = self._build_corpus_cache_key(corpus=corpus)
        with self._cache_lock:
            cached = self._corpus_embeddings_cache.get(key)
            if cached is not None:
                self._corpus_embeddings_cache.move_to_end(key)
                return cached
        embeddings = self._encode_corpus_embeddings(corpus=corpus)
        with self._cache_lock:
            self._corpus_embeddings_cache[key] = embeddings
            self._corpus_embeddings_cache.move_to_end(key)
            while len(self._corpus_embeddings_cache) > self._corpus_cache_max_items:
                self._corpus_embeddings_cache.popitem(last=False)
        return embeddings

    def _get_or_encode_query_embeddings(self, *, queries: list[str]) -> object | None:
        import numpy as np

        if self._model is None:
            return None
        if not queries:
            return np.zeros((0, 0), dtype=np.float32)
        resolved: list[object | None] = [None for _ in queries]
        missing_keys: list[str] = []
        missing_queries: list[str] = []
        key_to_slots: dict[str, list[int]] = {}
        with self._cache_lock:
            for slot_idx, query in enumerate(queries):
                key = self._build_query_cache_key(query=query)
                cached = self._query_embedding_cache.get(key)
                if cached is not None:
                    self._query_embedding_cache.move_to_end(key)
                    resolved[slot_idx] = cached
                    continue
                slots = key_to_slots.setdefault(key, [])
                slots.append(slot_idx)
                if len(slots) == 1:
                    missing_keys.append(key)
                    missing_queries.append(query)
        if missing_queries:
            encoded = self._encode_sentences(missing_queries)
            with self._cache_lock:
                for key, embedding in zip(missing_keys, encoded, strict=False):
                    self._query_embedding_cache[key] = embedding
                    self._query_embedding_cache.move_to_end(key)
                    while (
                        len(self._query_embedding_cache) > self._query_cache_max_items
                    ):
                        self._query_embedding_cache.popitem(last=False)
                    for slot_idx in key_to_slots.get(key, []):
                        resolved[slot_idx] = embedding
        if any(item is None for item in resolved):
            return None
        resolved_embeddings = [item for item in resolved if item is not None]
        return np.stack(resolved_embeddings)

    def _encode_corpus_embeddings(self, *, corpus: list[str]) -> object:
        import numpy as np

        if self._model is None:
            return np.zeros((0, 0), dtype=np.float32)
        sentence_to_unique_idx: dict[str, int] = {}
        unique_sentences: list[str] = []
        row_to_unique_idx: list[int] = []
        for sentence in corpus:
            existing_idx = sentence_to_unique_idx.get(sentence)
            if existing_idx is None:
                existing_idx = len(unique_sentences)
                sentence_to_unique_idx[sentence] = existing_idx
                unique_sentences.append(sentence)
            row_to_unique_idx.append(existing_idx)
        unique_embeddings = self._encode_sentences(unique_sentences)
        row_embeddings = np.asarray(
            [unique_embeddings[idx] for idx in row_to_unique_idx],
            dtype=unique_embeddings.dtype,
        )
        return row_embeddings

    def _encode_sentences(self, sentences: list[str]) -> object:
        if self._model is None:
            return []
        kwargs = {
            "convert_to_numpy": True,
            "normalize_embeddings": True,
        }
        try:
            return self._model.encode(  # type: ignore[call-arg]
                sentences,
                show_progress_bar=False,
                **kwargs,
            )
        except TypeError:
            return self._model.encode(  # type: ignore[call-arg]
                sentences,
                **kwargs,
            )

    def _build_corpus_cache_key(self, *, corpus: list[str]) -> tuple[int, str]:
        digest = hashlib.blake2b(digest_size=16)
        for sentence in corpus:
            digest.update(sentence.encode("utf-8", errors="ignore"))
            digest.update(b"\x1f")
        return (len(corpus), digest.hexdigest())

    def _build_query_cache_key(self, *, query: str) -> str:
        digest = hashlib.blake2b(digest_size=16)
        digest.update(query.encode("utf-8", errors="ignore"))
        return digest.hexdigest()
