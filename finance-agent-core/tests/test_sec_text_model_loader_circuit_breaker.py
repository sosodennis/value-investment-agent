from __future__ import annotations

import sys
import types

import numpy as np
import torch

from src.agents.fundamental.forward_signals.infrastructure.sec_xbrl.fls_filter import (
    _FLSClassifier,
)
from src.agents.fundamental.forward_signals.infrastructure.sec_xbrl.hybrid_retriever import (
    _DenseRetriever,
)


def test_fls_classifier_stops_reloading_after_first_failure(
    monkeypatch,
) -> None:
    load_attempts = {"tokenizer": 0}

    class _FakeTokenizer:
        @staticmethod
        def from_pretrained(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            load_attempts["tokenizer"] += 1
            raise RuntimeError("offline")

    class _FakeModel:
        @staticmethod
        def from_pretrained(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("offline")

    fake_transformers = types.SimpleNamespace(
        AutoTokenizer=_FakeTokenizer,
        AutoModelForSequenceClassification=_FakeModel,
    )
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    classifier = _FLSClassifier()
    assert classifier._ensure_loaded() is False
    assert classifier._ensure_loaded() is False
    assert load_attempts["tokenizer"] == 1


def test_dense_retriever_stops_reloading_after_first_failure(
    monkeypatch,
) -> None:
    load_attempts = {"model": 0}

    class _FakeSentenceTransformer:
        def __init__(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            load_attempts["model"] += 1
            raise RuntimeError("offline")

    fake_sentence_transformers = types.SimpleNamespace(
        SentenceTransformer=_FakeSentenceTransformer,
    )
    monkeypatch.setitem(
        sys.modules, "sentence_transformers", fake_sentence_transformers
    )

    retriever = _DenseRetriever()
    assert retriever._ensure_loaded() is False
    assert retriever._ensure_loaded() is False
    assert load_attempts["model"] == 1


def test_fls_prefilter_caps_model_input_and_keeps_forward_anchor(monkeypatch) -> None:
    monkeypatch.setenv("SEC_TEXT_FLS_PREFILTER_MAX_SENTENCES", "64")
    monkeypatch.setenv("SEC_TEXT_FLS_PREFILTER_CONTEXT_WINDOW", "1")
    classifier = _FLSClassifier()
    sentences = [f"Historical accounting discussion {idx}." for idx in range(80)]
    sentences[40] = "Management expects higher revenue next year."
    sentences[41] = "The company guides to improve operating margin by 100 bps."
    filtered = classifier._prefilter_for_inference(sentences)
    assert len(filtered) <= 64
    assert any("expects higher revenue" in sentence.lower() for sentence in filtered)


def test_fls_prefilter_uses_default_cap_for_dense_forward_corpus() -> None:
    classifier = _FLSClassifier()
    sentences = [
        f"Management expects higher revenue for period {idx}." for idx in range(180)
    ]
    filtered = classifier._prefilter_for_inference(sentences)
    assert len(filtered) == 120


def test_fls_classifier_batches_inference_with_configured_batch_size(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SEC_TEXT_FLS_BATCH_SIZE", "3")
    batch_sizes: list[int] = []

    class _FakeTokenizer:
        def __call__(  # type: ignore[no-untyped-def]
            self,
            texts: list[str],
            *,
            return_tensors: str,
            padding: bool,
            truncation: bool,
            max_length: int,
        ) -> dict[str, torch.Tensor]:
            assert return_tensors == "pt"
            assert padding is True
            assert truncation is True
            assert max_length >= 64
            batch_sizes.append(len(texts))
            batch = len(texts)
            return {
                "input_ids": torch.ones((batch, 4), dtype=torch.long),
                "attention_mask": torch.ones((batch, 4), dtype=torch.long),
            }

    class _FakeModel:
        def __call__(self, **inputs: torch.Tensor) -> object:
            batch = int(inputs["input_ids"].shape[0])
            logits = torch.zeros((batch, 3), dtype=torch.float32)
            logits[:, 1] = 1.0
            return types.SimpleNamespace(logits=logits)

    classifier = _FLSClassifier()
    classifier._loaded = True
    classifier._tokenizer = _FakeTokenizer()
    classifier._model = _FakeModel()
    classifier._keep_label_ids = {1}
    sentences = [f"Management expects guidance update {idx}." for idx in range(7)]

    filtered, stats = classifier.keep_forward_sentences_with_stats(sentences)

    assert len(filtered) == 7
    assert batch_sizes == [3, 3, 1]
    assert stats.batches == 3
    assert stats.sentences_scored == 7


def test_fls_classifier_length_bucketing_preserves_output_alignment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SEC_TEXT_FLS_BATCH_SIZE", "3")
    observed_batches: list[list[int]] = []

    class _FakeTokenizer:
        def __call__(  # type: ignore[no-untyped-def]
            self,
            texts: list[str],
            *,
            return_tensors: str,
            padding: bool,
            truncation: bool,
            max_length: int,
        ) -> dict[str, torch.Tensor]:
            assert return_tensors == "pt"
            assert padding is True
            assert truncation is True
            assert max_length >= 64
            ids = [int(text.rsplit("id=", maxsplit=1)[1]) for text in texts]
            observed_batches.append(ids)
            values = torch.tensor(ids, dtype=torch.long).reshape(len(ids), 1)
            return {
                "input_ids": values,
                "attention_mask": torch.ones((len(ids), 1), dtype=torch.long),
            }

    class _FakeModel:
        def __call__(self, **inputs: torch.Tensor) -> object:
            ids = inputs["input_ids"].reshape(-1)
            logits = torch.zeros((ids.shape[0], 2), dtype=torch.float32)
            odd_mask = (ids % 2).to(torch.bool)
            logits[~odd_mask, 0] = 1.0
            logits[odd_mask, 1] = 1.0
            return types.SimpleNamespace(logits=logits)

    classifier = _FLSClassifier()
    classifier._loaded = True
    classifier._tokenizer = _FakeTokenizer()
    classifier._model = _FakeModel()
    classifier._keep_label_ids = {1}
    sentences = [
        "short id=0",
        "very long guidance sentence repeated repeated repeated id=1",
        "medium length id=2",
        "extremely long management outlook sentence repeated repeated repeated repeated id=3",
        "tiny id=4",
        "long demand forecast sentence repeated repeated id=5",
        "brief id=6",
    ]

    filtered, stats = classifier.keep_forward_sentences_with_stats(sentences)

    assert stats.batches == 3
    assert observed_batches[0] == [3, 1, 5]
    assert filtered == [sentences[1], sentences[3], sentences[5]]


def test_fls_classifier_sentence_cache_reuses_predictions_across_calls() -> None:
    tokenizer_calls = {"count": 0}

    class _FakeTokenizer:
        def __call__(  # type: ignore[no-untyped-def]
            self,
            texts: list[str],
            *,
            return_tensors: str,
            padding: bool,
            truncation: bool,
            max_length: int,
        ) -> dict[str, torch.Tensor]:
            assert return_tensors == "pt"
            assert padding is True
            assert truncation is True
            assert max_length >= 64
            tokenizer_calls["count"] += 1
            batch = len(texts)
            return {
                "input_ids": torch.ones((batch, 4), dtype=torch.long),
                "attention_mask": torch.ones((batch, 4), dtype=torch.long),
            }

    class _FakeModel:
        def __call__(self, **inputs: torch.Tensor) -> object:
            batch = int(inputs["input_ids"].shape[0])
            logits = torch.zeros((batch, 2), dtype=torch.float32)
            logits[:, 1] = 1.0
            return types.SimpleNamespace(logits=logits)

    classifier = _FLSClassifier()
    classifier._loaded = True
    classifier._tokenizer = _FakeTokenizer()
    classifier._model = _FakeModel()
    classifier._keep_label_ids = {1}
    sentences = [
        "Management expects stronger demand in Q4.",
        "The company guides to higher margin next year.",
        "Management expects stronger demand in Q4.",
    ]

    first_filtered, first_stats = classifier.keep_forward_sentences_with_stats(
        sentences
    )
    second_filtered, second_stats = classifier.keep_forward_sentences_with_stats(
        sentences
    )

    assert len(first_filtered) == len(sentences)
    assert len(second_filtered) == len(sentences)
    assert first_stats.cache_hits == 0
    assert first_stats.cache_misses == 2
    assert first_stats.sentences_scored == 2
    assert second_stats.cache_hits == 3
    assert second_stats.cache_misses == 0
    assert second_stats.sentences_scored == 0
    assert second_stats.batches == 0
    assert tokenizer_calls["count"] == 1


def test_fls_classifier_warmup_runs_dummy_inference(monkeypatch) -> None:
    load_attempts = {"tokenizer": 0, "model": 0}
    tokenizer_inputs: list[list[str]] = []

    class _FakeTokenizer:
        def __call__(  # type: ignore[no-untyped-def]
            self,
            texts: list[str],
            *,
            return_tensors: str,
            padding: bool,
            truncation: bool,
            max_length: int,
        ) -> dict[str, torch.Tensor]:
            assert return_tensors == "pt"
            assert padding is True
            assert truncation is True
            assert max_length >= 64
            tokenizer_inputs.append(list(texts))
            batch = len(texts)
            return {
                "input_ids": torch.ones((batch, 4), dtype=torch.long),
                "attention_mask": torch.ones((batch, 4), dtype=torch.long),
            }

    class _FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            load_attempts["tokenizer"] += 1
            return _FakeTokenizer()

    class _FakeModel:
        def __init__(self) -> None:
            self.config = types.SimpleNamespace(id2label={0: "not_fls", 1: "fls"})

        def eval(self) -> None:
            return None

        def __call__(self, **inputs: torch.Tensor) -> object:
            batch = int(inputs["input_ids"].shape[0])
            logits = torch.zeros((batch, 2), dtype=torch.float32)
            logits[:, 1] = 1.0
            return types.SimpleNamespace(logits=logits)

    class _FakeAutoModel:
        @staticmethod
        def from_pretrained(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            load_attempts["model"] += 1
            return _FakeModel()

    fake_transformers = types.SimpleNamespace(
        AutoTokenizer=_FakeAutoTokenizer,
        AutoModelForSequenceClassification=_FakeAutoModel,
    )
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    classifier = _FLSClassifier()
    result = classifier.warmup()

    assert result["enabled"] is True
    assert result["loaded"] is True
    assert result["batches"] == 1
    assert float(result["inference_ms"]) >= 0.0
    assert load_attempts == {"tokenizer": 1, "model": 1}
    assert len(tokenizer_inputs) == 1
    assert tokenizer_inputs[0][0].startswith("Management expects higher revenue")


def test_fls_classifier_warmup_reports_load_error(monkeypatch) -> None:
    class _FakeTokenizer:
        @staticmethod
        def from_pretrained(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("offline")

    class _FakeModel:
        @staticmethod
        def from_pretrained(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("offline")

    fake_transformers = types.SimpleNamespace(
        AutoTokenizer=_FakeTokenizer,
        AutoModelForSequenceClassification=_FakeModel,
    )
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    classifier = _FLSClassifier()
    result = classifier.warmup()

    assert result["enabled"] is True
    assert result["loaded"] is False
    assert result["batches"] == 0
    assert "offline" in str(result.get("error", ""))


def test_dense_retriever_caches_corpus_embeddings_for_repeated_queries() -> None:
    class _FakeModel:
        def __init__(self) -> None:
            self.encode_inputs: list[list[str]] = []

        def encode(
            self,
            texts: list[str],
            *,
            convert_to_numpy: bool,
            normalize_embeddings: bool,
        ) -> np.ndarray:
            assert convert_to_numpy is True
            assert normalize_embeddings is True
            self.encode_inputs.append(list(texts))
            if len(texts) == 1:
                return np.array([[0.9, 0.1]], dtype=np.float32)
            vectors = [[float(idx + 1), 1.0] for idx in range(len(texts))]
            return np.array(vectors, dtype=np.float32)

    retriever = _DenseRetriever()
    retriever._loaded = True
    retriever._model = _FakeModel()

    corpus = [
        "Management expects higher revenue.",
        "Historical accounting discussion.",
        "Guidance includes margin improvement.",
    ]
    retriever.rank(query="revenue guidance", corpus=corpus)
    retriever.rank(query="margin outlook", corpus=corpus)

    model = retriever._model
    assert isinstance(model, _FakeModel)
    corpus_encode_calls = [inputs for inputs in model.encode_inputs if len(inputs) == 3]
    query_encode_calls = [inputs for inputs in model.encode_inputs if len(inputs) == 1]
    assert len(corpus_encode_calls) == 1
    assert len(query_encode_calls) == 2


def test_dense_retriever_reencodes_when_corpus_changes() -> None:
    class _FakeModel:
        def __init__(self) -> None:
            self.encode_inputs: list[list[str]] = []

        def encode(
            self,
            texts: list[str],
            *,
            convert_to_numpy: bool,
            normalize_embeddings: bool,
        ) -> np.ndarray:
            assert convert_to_numpy is True
            assert normalize_embeddings is True
            self.encode_inputs.append(list(texts))
            if len(texts) == 1:
                return np.array([[0.8, 0.2]], dtype=np.float32)
            vectors = [[float(idx + 1), 1.0] for idx in range(len(texts))]
            return np.array(vectors, dtype=np.float32)

    retriever = _DenseRetriever()
    retriever._loaded = True
    retriever._model = _FakeModel()

    first_corpus = [
        "Management expects higher revenue.",
        "Guidance includes margin improvement.",
    ]
    second_corpus = [
        "Management expects higher revenue.",
        "Guidance includes margin expansion.",
    ]
    retriever.rank(query="revenue guidance", corpus=first_corpus)
    retriever.rank(query="margin outlook", corpus=second_corpus)

    model = retriever._model
    assert isinstance(model, _FakeModel)
    corpus_encode_calls = [inputs for inputs in model.encode_inputs if len(inputs) == 2]
    assert len(corpus_encode_calls) == 2


def test_dense_retriever_caches_repeated_query_embedding() -> None:
    class _FakeModel:
        def __init__(self) -> None:
            self.encode_inputs: list[list[str]] = []

        def encode(
            self,
            texts: list[str],
            *,
            convert_to_numpy: bool,
            normalize_embeddings: bool,
        ) -> np.ndarray:
            assert convert_to_numpy is True
            assert normalize_embeddings is True
            self.encode_inputs.append(list(texts))
            if len(texts) == 1:
                return np.array([[0.6, 0.4]], dtype=np.float32)
            vectors = [[float(idx + 1), 1.0] for idx in range(len(texts))]
            return np.array(vectors, dtype=np.float32)

    retriever = _DenseRetriever()
    retriever._loaded = True
    retriever._model = _FakeModel()

    corpus = [
        "Management expects higher revenue.",
        "Guidance includes margin improvement.",
        "Historical accounting discussion.",
    ]
    retriever.rank(query="revenue guidance outlook", corpus=corpus)
    retriever.rank(query="revenue guidance outlook", corpus=corpus)

    model = retriever._model
    assert isinstance(model, _FakeModel)
    query_encode_calls = [
        inputs
        for inputs in model.encode_inputs
        if inputs == ["revenue guidance outlook"]
    ]
    assert len(query_encode_calls) == 1


def test_dense_retriever_deduplicates_corpus_before_encoding() -> None:
    class _FakeModel:
        def __init__(self) -> None:
            self.encode_inputs: list[list[str]] = []

        def encode(
            self,
            texts: list[str],
            *,
            convert_to_numpy: bool,
            normalize_embeddings: bool,
        ) -> np.ndarray:
            assert convert_to_numpy is True
            assert normalize_embeddings is True
            self.encode_inputs.append(list(texts))
            if len(texts) == 1:
                return np.array([[0.5, 0.5]], dtype=np.float32)
            vectors = [[float(idx + 1), 1.0] for idx in range(len(texts))]
            return np.array(vectors, dtype=np.float32)

    retriever = _DenseRetriever()
    retriever._loaded = True
    retriever._model = _FakeModel()

    corpus = [
        "Management expects higher revenue.",
        "Management expects higher revenue.",
        "Guidance includes margin improvement.",
        "Management expects higher revenue.",
    ]
    retriever.rank(query="revenue guidance", corpus=corpus)

    model = retriever._model
    assert isinstance(model, _FakeModel)
    corpus_encode_calls = [inputs for inputs in model.encode_inputs if len(inputs) > 1]
    assert len(corpus_encode_calls) == 1
    assert len(corpus_encode_calls[0]) == 2


def test_dense_retriever_batches_missing_query_embeddings() -> None:
    class _FakeModel:
        def __init__(self) -> None:
            self.encode_inputs: list[list[str]] = []

        def encode(
            self,
            texts: list[str],
            *,
            convert_to_numpy: bool,
            normalize_embeddings: bool,
        ) -> np.ndarray:
            assert convert_to_numpy is True
            assert normalize_embeddings is True
            self.encode_inputs.append(list(texts))
            if len(texts) == 3:
                vectors = [[float(idx + 1), 1.0] for idx in range(len(texts))]
                return np.array(vectors, dtype=np.float32)
            vectors = [
                [0.9, 0.1] if "revenue" in text else [0.1, 0.9] for text in texts
            ]
            return np.array(vectors, dtype=np.float32)

    retriever = _DenseRetriever()
    retriever._loaded = True
    retriever._model = _FakeModel()

    corpus = [
        "Management expects higher revenue.",
        "Guidance includes margin improvement.",
        "Historical accounting discussion.",
    ]
    rankings = retriever.rank_many(
        queries=["revenue growth outlook", "margin outlook guidance"],
        corpus=corpus,
    )

    model = retriever._model
    assert isinstance(model, _FakeModel)
    assert len(rankings) == 2
    query_batch_calls = [
        inputs
        for inputs in model.encode_inputs
        if inputs == ["revenue growth outlook", "margin outlook guidance"]
    ]
    assert len(query_batch_calls) == 1
