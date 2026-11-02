from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Callable


def sentence_cache_key(sentence: str) -> str:
    normalized = " ".join(sentence.split())
    digest = hashlib.blake2b(
        normalized.encode("utf-8", errors="ignore"),
        digest_size=16,
    ).hexdigest()
    return f"{len(normalized)}:{digest}"


def predict_keep_flags_with_cache(
    *,
    sentences: list[str],
    prediction_cache: OrderedDict[str, bool],
    cache_lock: threading.Lock,
    cache_max_items: int,
    predict_missing_fn: Callable[[list[str]], tuple[list[bool], int]],
) -> tuple[list[bool], int, int, int]:
    if not sentences:
        return [], 0, 0, 0

    resolved: list[bool | None] = [None for _ in sentences]
    missing_keys: list[str] = []
    missing_sentences: list[str] = []
    key_to_slots: dict[str, list[int]] = {}
    cache_hits = 0

    with cache_lock:
        for slot_idx, sentence in enumerate(sentences):
            key = sentence_cache_key(sentence)
            cached = prediction_cache.get(key)
            if cached is not None:
                prediction_cache.move_to_end(key)
                resolved[slot_idx] = cached
                cache_hits += 1
                continue
            slots = key_to_slots.setdefault(key, [])
            slots.append(slot_idx)
            if len(slots) == 1:
                missing_keys.append(key)
                missing_sentences.append(sentence)

    batch_count = 0
    if missing_sentences:
        predicted_missing, batch_count = predict_missing_fn(missing_sentences)
        if len(predicted_missing) != len(missing_sentences):
            raise ValueError("FLS prediction count did not match input count")
        with cache_lock:
            for key, keep in zip(missing_keys, predicted_missing, strict=True):
                prediction_cache[key] = keep
                prediction_cache.move_to_end(key)
                while len(prediction_cache) > cache_max_items:
                    prediction_cache.popitem(last=False)
                for slot_idx in key_to_slots[key]:
                    resolved[slot_idx] = keep

    if any(keep is None for keep in resolved):
        raise ValueError("FLS cache failed to resolve every input")

    return (
        [bool(keep) for keep in resolved],
        batch_count,
        cache_hits,
        len(missing_sentences),
    )
