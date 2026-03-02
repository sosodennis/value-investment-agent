from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict

from src.shared.kernel.tools.logger import get_logger, log_event

from .fls_filter_inference_service import (
    predict_keep_flags_torch,
    predict_labels_with_cache,
    resolve_keep_label_ids,
)
from .fls_filter_prefilter_service import prefilter_for_inference, rule_based_filter
from .fls_filter_stats import FLSFilterStats

logger = get_logger(__name__)

_FLS_MODEL_NAME = os.getenv("SEC_TEXT_FLS_MODEL", "yiyanghkust/finbert-fls")
_HF_LOCAL_FILES_ONLY = os.getenv("HF_LOCAL_FILES_ONLY", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
_FLS_FILTER_DISABLED = os.getenv("SEC_TEXT_ENABLE_FLS_FILTER", "1").strip().lower() in {
    "0",
    "false",
    "no",
}
_FLS_MAX_LENGTH = 192
_FLS_BATCH_SIZE = 32
_FLS_PREFILTER_MAX_SENTENCES = 120
_FLS_PREFILTER_CONTEXT_WINDOW = 1
_FLS_WARMUP_SENTENCE = "Management expects higher revenue growth next year."
_FLS_SENTENCE_CACHE_MAX_ITEMS = 4096


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


class _FLSClassifier:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._loaded = False
        self._disabled = _FLS_FILTER_DISABLED
        self._tokenizer: object | None = None
        self._model: object | None = None
        self._backend: str = "none"
        self._keep_label_ids: set[int] = set()
        self._load_error: str | None = None
        self._sentence_prediction_cache: OrderedDict[str, int] = OrderedDict()
        self._sentence_cache_max_items = _env_int(
            "SEC_TEXT_FLS_SENTENCE_CACHE_MAX_ITEMS",
            _FLS_SENTENCE_CACHE_MAX_ITEMS,
            minimum=64,
        )

    def keep_forward_sentences(self, sentences: list[str]) -> list[str]:
        selected, _stats = self.keep_forward_sentences_with_stats(sentences)
        return selected

    def keep_forward_sentences_with_stats(
        self,
        sentences: list[str],
    ) -> tuple[list[str], FLSFilterStats]:
        stats = FLSFilterStats()
        if not sentences:
            return [], stats

        model_input_sentences = self._prefilter_for_inference(sentences)
        stats.prefilter_selected = len(model_input_sentences)

        if self._disabled:
            return self._rule_based_filter(sentences), stats

        loaded, model_load_ms = self._ensure_loaded_with_timing()
        stats.model_load_ms += model_load_ms
        if not loaded:
            return self._rule_based_filter(sentences), stats

        inference_started = time.perf_counter()
        try:
            predictions, batch_count, cache_hits, cache_misses = (
                self._predict_keep_flags(model_input_sentences)
            )
            stats.inference_ms += (time.perf_counter() - inference_started) * 1000.0
            stats.sentences_scored += cache_misses
            stats.batches += batch_count
            stats.cache_hits += cache_hits
            stats.cache_misses += cache_misses
            selected = [
                sentence
                for sentence, keep in zip(
                    model_input_sentences,
                    predictions,
                    strict=False,
                )
                if keep
            ]
            if selected:
                return selected, stats
            return self._rule_based_filter(sentences), stats
        except Exception as exc:
            stats.inference_ms += (time.perf_counter() - inference_started) * 1000.0
            log_event(
                logger,
                event="fundamental_fls_filter_inference_failed",
                message="finbert fls inference failed; fallback lexical filter is active",
                fields={"exception": str(exc)},
            )
            return self._rule_based_filter(sentences), stats

    def warmup(self) -> dict[str, float | int | bool | str]:
        if self._disabled:
            return {
                "enabled": False,
                "loaded": False,
                "model_load_ms": 0.0,
                "inference_ms": 0.0,
                "batches": 0,
            }

        loaded, model_load_ms = self._ensure_loaded_with_timing()
        if not loaded:
            return {
                "enabled": True,
                "loaded": False,
                "model_load_ms": round(model_load_ms, 3),
                "inference_ms": 0.0,
                "batches": 0,
                "error": self._load_error or "unknown",
            }

        inference_started = time.perf_counter()
        try:
            _predictions, batch_count, _cache_hits, _cache_misses = (
                self._predict_keep_flags([_FLS_WARMUP_SENTENCE])
            )
            inference_ms = (time.perf_counter() - inference_started) * 1000.0
            return {
                "enabled": True,
                "loaded": True,
                "model_load_ms": round(model_load_ms, 3),
                "inference_ms": round(inference_ms, 3),
                "batches": batch_count,
            }
        except Exception as exc:
            inference_ms = (time.perf_counter() - inference_started) * 1000.0
            return {
                "enabled": True,
                "loaded": True,
                "model_load_ms": round(model_load_ms, 3),
                "inference_ms": round(inference_ms, 3),
                "batches": 0,
                "error": str(exc),
            }

    def _ensure_loaded(self) -> bool:
        loaded, _load_ms = self._ensure_loaded_with_timing()
        return loaded

    def _ensure_loaded_with_timing(self) -> tuple[bool, float]:
        if self._loaded:
            return True, 0.0
        if self._load_error is not None:
            return False, 0.0

        with self._lock:
            if self._loaded:
                return True, 0.0
            if self._load_error is not None:
                return False, 0.0

            started = time.perf_counter()
            try:
                from transformers import (
                    AutoModelForSequenceClassification,
                    AutoTokenizer,
                )

                tokenizer = AutoTokenizer.from_pretrained(
                    _FLS_MODEL_NAME,
                    local_files_only=_HF_LOCAL_FILES_ONLY,
                )
                model = AutoModelForSequenceClassification.from_pretrained(
                    _FLS_MODEL_NAME,
                    local_files_only=_HF_LOCAL_FILES_ONLY,
                )
                model.eval()

                keep_ids = resolve_keep_label_ids(model)
                self._tokenizer = tokenizer
                self._model = model
                self._backend = "torch"
                self._keep_label_ids = keep_ids
                self._loaded = True

                log_event(
                    logger,
                    event="fundamental_fls_filter_model_loaded",
                    message="finbert fls model loaded for sentence filtering",
                    fields={
                        "model": _FLS_MODEL_NAME,
                        "local_files_only": _HF_LOCAL_FILES_ONLY,
                        "keep_label_ids": sorted(keep_ids),
                        "backend": "torch",
                    },
                )
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                return True, elapsed_ms
            except Exception as exc:
                self._load_error = str(exc)
                log_event(
                    logger,
                    event="fundamental_fls_filter_model_unavailable",
                    message="finbert fls model unavailable; fallback lexical filter is active",
                    fields={
                        "model": _FLS_MODEL_NAME,
                        "local_files_only": _HF_LOCAL_FILES_ONLY,
                        "backend": self._backend,
                        "exception": self._load_error,
                    },
                )
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                return False, elapsed_ms

    def _predict_keep_flags(
        self,
        sentences: list[str],
    ) -> tuple[list[bool], int, int, int]:
        if self._tokenizer is None or self._model is None:
            return [False for _ in sentences], 0, 0, 0

        (
            predicted,
            batch_count,
            cache_hits,
            cache_misses,
        ) = self._predict_labels_with_cache(sentences=sentences)
        keep_flags = [int(label_id) in self._keep_label_ids for label_id in predicted]
        return keep_flags, batch_count, cache_hits, cache_misses

    def _predict_labels_with_cache(
        self,
        *,
        sentences: list[str],
    ) -> tuple[list[int], int, int, int]:
        return predict_labels_with_cache(
            sentences=sentences,
            prediction_cache=self._sentence_prediction_cache,
            cache_lock=self._cache_lock,
            cache_max_items=self._sentence_cache_max_items,
            predict_missing_fn=(
                lambda missing_sentences: self._predict_keep_flags_torch(
                    sentences=missing_sentences
                )
            ),
        )

    def _predict_keep_flags_torch(
        self,
        *,
        sentences: list[str],
    ) -> tuple[list[int], int]:
        if self._tokenizer is None or self._model is None:
            return [0 for _ in sentences], 0

        max_length = _env_int("SEC_TEXT_FLS_MAX_LENGTH", _FLS_MAX_LENGTH, minimum=64)
        batch_size = _env_int("SEC_TEXT_FLS_BATCH_SIZE", _FLS_BATCH_SIZE, minimum=1)
        return predict_keep_flags_torch(
            sentences=sentences,
            tokenizer=self._tokenizer,
            model=self._model,
            max_length=max_length,
            batch_size=batch_size,
        )

    def _prefilter_for_inference(self, sentences: list[str]) -> list[str]:
        if not sentences:
            return []

        max_sentences = _env_int(
            "SEC_TEXT_FLS_PREFILTER_MAX_SENTENCES",
            _FLS_PREFILTER_MAX_SENTENCES,
            minimum=64,
        )
        context_window = _env_int(
            "SEC_TEXT_FLS_PREFILTER_CONTEXT_WINDOW",
            _FLS_PREFILTER_CONTEXT_WINDOW,
            minimum=0,
        )
        return prefilter_for_inference(
            sentences,
            max_sentences=max_sentences,
            context_window=context_window,
        )

    def _rule_based_filter(self, sentences: list[str]) -> list[str]:
        return rule_based_filter(sentences)


_CLASSIFIER = _FLSClassifier()


def filter_forward_looking_sentences(sentences: list[str]) -> list[str]:
    return _CLASSIFIER.keep_forward_sentences(sentences)


def filter_forward_looking_sentences_with_stats(
    sentences: list[str],
) -> tuple[list[str], dict[str, float | int]]:
    selected, stats = _CLASSIFIER.keep_forward_sentences_with_stats(sentences)
    return selected, stats.to_fields()


def warmup_forward_looking_filter() -> dict[str, float | int | bool | str]:
    return _CLASSIFIER.warmup()
