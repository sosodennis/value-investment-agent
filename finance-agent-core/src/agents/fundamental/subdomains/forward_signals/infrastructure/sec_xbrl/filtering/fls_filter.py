from __future__ import annotations

import math
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import Protocol

from src.model_inference.entrypoint import FLSResult
from src.shared.kernel.tools.logger import get_logger, log_event

from .fls_filter_inference_service import predict_keep_flags_with_cache
from .fls_filter_prefilter_service import prefilter_for_inference, rule_based_filter
from .fls_filter_stats import FLSFilterStats

logger = get_logger(__name__)

_FLS_FILTER_DISABLED = os.getenv("SEC_TEXT_ENABLE_FLS_FILTER", "1").strip().lower() in {
    "0",
    "false",
    "no",
}
_FLS_BATCH_SIZE = 32
_FLS_PREFILTER_MAX_SENTENCES = 120
_FLS_PREFILTER_CONTEXT_WINDOW = 1
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


class FLSPredictionPort(Protocol):
    def fls_predictions(self, sentences: Sequence[str]) -> FLSResult: ...


FilterWithStats = Callable[[list[str]], tuple[list[str], dict[str, float | int]]]


class _FLSClassifier:
    def __init__(self, inference: FLSPredictionPort | None = None) -> None:
        self._inference = inference
        self._disabled = _FLS_FILTER_DISABLED
        self._cache_lock = threading.Lock()
        self._sentence_prediction_cache: OrderedDict[str, bool] = OrderedDict()
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

        if self._disabled or self._inference is None:
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
                    strict=True,
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
                message="FLS service inference failed; lexical filtering is active",
                fields={"exception_type": type(exc).__name__},
            )
            return self._rule_based_filter(sentences), stats

    def _predict_keep_flags(
        self,
        sentences: list[str],
    ) -> tuple[list[bool], int, int, int]:
        return predict_keep_flags_with_cache(
            sentences=sentences,
            prediction_cache=self._sentence_prediction_cache,
            cache_lock=self._cache_lock,
            cache_max_items=self._sentence_cache_max_items,
            predict_missing_fn=self._predict_remote,
        )

    def _predict_remote(self, sentences: list[str]) -> tuple[list[bool], int]:
        if self._inference is None:
            return [False for _ in sentences], 0
        result = self._inference.fls_predictions(sentences)
        if len(result.predictions) != len(sentences):
            raise ValueError("FLS inference result cardinality mismatch")
        batch_count = sum(
            math.ceil(len(sentences[start : start + 120]) / _FLS_BATCH_SIZE)
            for start in range(0, len(sentences), 120)
        )
        return [prediction.keep for prediction in result.predictions], batch_count

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


def build_forward_looking_filter(inference: FLSPredictionPort) -> FilterWithStats:
    classifier = _FLSClassifier(inference)
    return classifier.keep_forward_sentences_with_stats


_DEFAULT_CLASSIFIER = _FLSClassifier()


def filter_forward_looking_sentences(sentences: list[str]) -> list[str]:
    return _DEFAULT_CLASSIFIER.keep_forward_sentences(sentences)


def filter_forward_looking_sentences_with_stats(
    sentences: list[str],
) -> tuple[list[str], dict[str, float | int]]:
    selected, stats = _DEFAULT_CLASSIFIER.keep_forward_sentences_with_stats(sentences)
    return selected, stats.to_fields()
