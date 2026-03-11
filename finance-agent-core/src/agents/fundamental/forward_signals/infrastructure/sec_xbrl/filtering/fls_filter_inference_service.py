from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Callable


def length_bucket_batches(sentences: list[str], *, batch_size: int) -> list[list[int]]:
    if not sentences:
        return []
    ordered = sorted(
        range(len(sentences)),
        key=lambda idx: (-len(sentences[idx]), idx),
    )
    batches: list[list[int]] = []
    safe_batch_size = max(1, batch_size)
    for start in range(0, len(ordered), safe_batch_size):
        batches.append(ordered[start : start + safe_batch_size])
    return batches


def sentence_cache_key(sentence: str) -> str:
    normalized = " ".join(sentence.split())
    digest = hashlib.blake2b(
        normalized.encode("utf-8", errors="ignore"),
        digest_size=16,
    ).hexdigest()
    return f"{len(normalized)}:{digest}"


def resolve_keep_label_ids(model: object) -> set[int]:
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


def predict_keep_flags_torch(
    *,
    sentences: list[str],
    tokenizer: object,
    model: object,
    max_length: int,
    batch_size: int,
) -> tuple[list[int], int]:
    import torch

    predicted: list[int] = [0 for _ in sentences]
    batch_count = 0
    for batch_indices in length_bucket_batches(sentences, batch_size=batch_size):
        sentence_batch = [sentences[idx] for idx in batch_indices]
        inputs = tokenizer(
            sentence_batch,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=max_length,
        )
        with torch.no_grad():
            outputs = model(**inputs)
        logits = outputs.logits
        batch_predicted = [int(label_id) for label_id in logits.argmax(dim=-1).tolist()]
        for slot_idx, sentence_idx in enumerate(batch_indices):
            if slot_idx < len(batch_predicted):
                predicted[sentence_idx] = batch_predicted[slot_idx]
        batch_count += 1
    return predicted, batch_count


def predict_labels_with_cache(
    *,
    sentences: list[str],
    prediction_cache: OrderedDict[str, int],
    cache_lock: threading.Lock,
    cache_max_items: int,
    predict_missing_fn: Callable[[list[str]], tuple[list[int], int]],
) -> tuple[list[int], int, int, int]:
    if not sentences:
        return [], 0, 0, 0

    resolved: list[int | None] = [None for _ in sentences]
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
        predicted_missing, batch_count = predict_missing_fn(missing_sentences)
        with cache_lock:
            for key, label_id in zip(missing_keys, predicted_missing, strict=False):
                label = int(label_id)
                prediction_cache[key] = label
                prediction_cache.move_to_end(key)
                while len(prediction_cache) > cache_max_items:
                    prediction_cache.popitem(last=False)
                for slot_idx in key_to_slots.get(key, []):
                    resolved[slot_idx] = label

    if any(label is None for label in resolved):
        return [0 for _ in sentences], batch_count, cache_hits, len(missing_sentences)

    predicted = [int(label) for label in resolved if label is not None]
    return predicted, batch_count, cache_hits, len(missing_sentences)
