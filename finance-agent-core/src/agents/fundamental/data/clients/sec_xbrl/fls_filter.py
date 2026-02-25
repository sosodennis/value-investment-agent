from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from src.shared.kernel.tools.logger import get_logger, log_event

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

_FORWARD_HINT = re.compile(
    r"\b(?:will|expects?|expecting|guidance|outlook|forecast|project(?:s|ed)?|"
    r"anticipat(?:e|es|ed)|target(?:s|ed)?)\b",
    re.IGNORECASE,
)


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


@dataclass
class _FLSFilterStats:
    model_load_ms: float = 0.0
    inference_ms: float = 0.0
    sentences_scored: int = 0
    prefilter_selected: int = 0
    batches: int = 0
    cache_hits: int = 0
    cache_misses: int = 0

    def to_fields(self) -> dict[str, float | int]:
        return {
            "model_load_ms": round(self.model_load_ms, 3),
            "inference_ms": round(self.inference_ms, 3),
            "sentences_scored": self.sentences_scored,
            "prefilter_selected": self.prefilter_selected,
            "batches": self.batches,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
        }


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
    ) -> tuple[list[str], _FLSFilterStats]:
        stats = _FLSFilterStats()
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
                keep_ids = self._resolve_keep_label_ids(model)
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

    def _resolve_keep_label_ids(self, model: object) -> set[int]:
        config = getattr(model, "config", None)
        raw_id2label = getattr(config, "id2label", None)
        if not isinstance(raw_id2label, dict):
            return {0, 1}
        keep_ids: set[int] = set()
        for raw_idx, raw_label in raw_id2label.items():
            label = str(raw_label).strip().lower().replace(" ", "").replace("_", "")
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                continue
            if "not" in label and "fls" in label:
                continue
            keep_ids.add(idx)
        return keep_ids if keep_ids else {0, 1}

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
        if not sentences:
            return [], 0, 0, 0
        resolved: list[int | None] = [None for _ in sentences]
        missing_keys: list[str] = []
        missing_sentences: list[str] = []
        key_to_slots: dict[str, list[int]] = {}
        cache_hits = 0
        with self._cache_lock:
            for slot_idx, sentence in enumerate(sentences):
                key = _sentence_cache_key(sentence)
                cached = self._sentence_prediction_cache.get(key)
                if cached is not None:
                    self._sentence_prediction_cache.move_to_end(key)
                    resolved[slot_idx] = int(cached)
                    cache_hits += 1
                    continue
                slots = key_to_slots.setdefault(key, [])
                slots.append(slot_idx)
                if len(slots) == 1:
                    missing_keys.append(key)
                    missing_sentences.append(sentence)
        batch_count = 0
        if missing_sentences:
            predicted_missing, batch_count = self._predict_keep_flags_torch(
                sentences=missing_sentences
            )
            with self._cache_lock:
                for key, label_id in zip(missing_keys, predicted_missing, strict=False):
                    label = int(label_id)
                    self._sentence_prediction_cache[key] = label
                    self._sentence_prediction_cache.move_to_end(key)
                    while (
                        len(self._sentence_prediction_cache)
                        > self._sentence_cache_max_items
                    ):
                        self._sentence_prediction_cache.popitem(last=False)
                    for slot_idx in key_to_slots.get(key, []):
                        resolved[slot_idx] = label
        if any(label is None for label in resolved):
            return (
                [0 for _ in sentences],
                batch_count,
                cache_hits,
                len(missing_sentences),
            )
        predicted = [int(label) for label in resolved if label is not None]
        return predicted, batch_count, cache_hits, len(missing_sentences)

    def _predict_keep_flags_torch(
        self, *, sentences: list[str]
    ) -> tuple[list[int], int]:
        import torch

        if self._tokenizer is None or self._model is None:
            return [0 for _ in sentences], 0
        max_length = _env_int("SEC_TEXT_FLS_MAX_LENGTH", _FLS_MAX_LENGTH, minimum=64)
        batch_size = _env_int("SEC_TEXT_FLS_BATCH_SIZE", _FLS_BATCH_SIZE, minimum=1)
        predicted: list[int] = [0 for _ in sentences]
        batch_count = 0
        for batch_indices in _length_bucket_batches(sentences, batch_size=batch_size):
            sentence_batch = [sentences[idx] for idx in batch_indices]
            inputs = self._tokenizer(
                sentence_batch,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=max_length,
            )
            with torch.no_grad():
                outputs = self._model(**inputs)
            logits = outputs.logits
            batch_predicted = [
                int(label_id) for label_id in logits.argmax(dim=-1).tolist()
            ]
            for slot_idx, sentence_idx in enumerate(batch_indices):
                if slot_idx < len(batch_predicted):
                    predicted[sentence_idx] = batch_predicted[slot_idx]
            batch_count += 1
        return predicted, batch_count

    def _prefilter_for_inference(self, sentences: list[str]) -> list[str]:
        if not sentences:
            return []
        max_sentences = _env_int(
            "SEC_TEXT_FLS_PREFILTER_MAX_SENTENCES",
            _FLS_PREFILTER_MAX_SENTENCES,
            minimum=64,
        )
        if len(sentences) <= max_sentences:
            return sentences
        context_window = _env_int(
            "SEC_TEXT_FLS_PREFILTER_CONTEXT_WINDOW",
            _FLS_PREFILTER_CONTEXT_WINDOW,
            minimum=0,
        )
        anchor_indices = [
            idx
            for idx, sentence in enumerate(sentences)
            if _FORWARD_HINT.search(sentence)
        ]
        if not anchor_indices:
            return sentences
        selected_indices: set[int] = set()
        for idx in anchor_indices:
            start = max(0, idx - context_window)
            end = min(len(sentences), idx + context_window + 1)
            selected_indices.update(range(start, end))
        if not selected_indices:
            return sentences
        if len(selected_indices) < max_sentences:
            remaining = [
                idx for idx in range(len(sentences)) if idx not in selected_indices
            ]
            ranked_remaining = sorted(
                remaining,
                key=lambda idx: self._forward_likelihood_score(sentences[idx]),
                reverse=True,
            )
            for idx in ranked_remaining:
                if len(selected_indices) >= max_sentences:
                    break
                if self._forward_likelihood_score(sentences[idx]) <= 0:
                    break
                selected_indices.add(idx)
        if len(selected_indices) > max_sentences:
            ranked_selected = sorted(
                selected_indices,
                key=lambda idx: (
                    self._forward_likelihood_score(sentences[idx]),
                    -idx,
                ),
                reverse=True,
            )
            selected_indices = set(ranked_selected[:max_sentences])
        ordered_indices = sorted(selected_indices)
        return [sentences[idx] for idx in ordered_indices]

    def _forward_likelihood_score(self, sentence: str) -> int:
        lowered = sentence.lower()
        score = 0
        if _FORWARD_HINT.search(sentence):
            score += 3
        if any(
            token in lowered
            for token in (
                "guidance",
                "outlook",
                "forecast",
                "expect",
                "target",
                "anticipat",
            )
        ):
            score += 2
        if any(
            token in lowered
            for token in (
                "revenue",
                "sales",
                "growth",
                "margin",
                "profit",
                "demand",
            )
        ):
            score += 1
        if any(char.isdigit() for char in lowered):
            score += 1
        return score

    def _rule_based_filter(self, sentences: list[str]) -> list[str]:
        candidates = [
            sentence for sentence in sentences if _FORWARD_HINT.search(sentence)
        ]
        return candidates if candidates else sentences


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


def _length_bucket_batches(sentences: list[str], *, batch_size: int) -> list[list[int]]:
    if not sentences:
        return []
    ordered = sorted(
        range(len(sentences)),
        key=lambda idx: (-len(sentences[idx]), idx),
    )
    batches: list[list[int]] = []
    for start in range(0, len(ordered), max(1, batch_size)):
        batches.append(ordered[start : start + max(1, batch_size)])
    return batches


def _sentence_cache_key(sentence: str) -> str:
    normalized = " ".join(sentence.split())
    digest = hashlib.blake2b(
        normalized.encode("utf-8", errors="ignore"),
        digest_size=16,
    ).hexdigest()
    return f"{len(normalized)}:{digest}"
