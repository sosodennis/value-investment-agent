from __future__ import annotations

import sys
import types

import numpy as np

from src.agents.fundamental.subdomains.forward_signals.infrastructure.sec_xbrl.filtering.fls_filter import (
    _FLSClassifier,
)
from src.agents.fundamental.subdomains.forward_signals.infrastructure.sec_xbrl.retrieval.hybrid_retriever import (
    _DenseRetriever,
)
from src.model_inference.entrypoint import (
    FLSPrediction,
    FLSResult,
    InferenceErrorCode,
    InferenceFailure,
)


def test_fls_classifier_without_inference_uses_lexical_fallback() -> None:
    classifier = _FLSClassifier()
    sentences = [
        "Historical accounting discussion.",
        "Management expects higher revenue next year.",
    ]

    filtered, stats = classifier.keep_forward_sentences_with_stats(sentences)

    assert filtered == [sentences[1]]
    assert stats.sentences_scored == 0


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
    class _FakeInference:
        def __init__(self) -> None:
            self.inputs: list[list[str]] = []

        def fls_predictions(self, sentences: list[str]) -> FLSResult:
            self.inputs.append(list(sentences))
            return FLSResult(
                predictions=tuple(
                    FLSPrediction(keep=True, confidence=0.9) for _sentence in sentences
                ),
                model_revision="test-revision",
            )

    inference = _FakeInference()
    classifier = _FLSClassifier(inference)
    sentences = [f"Management expects guidance update {idx}." for idx in range(7)]

    filtered, stats = classifier.keep_forward_sentences_with_stats(sentences)

    assert len(filtered) == 7
    assert inference.inputs == [sentences]
    assert stats.batches == 1
    assert stats.sentences_scored == 7


def test_fls_classifier_preserves_output_alignment() -> None:
    class _FakeInference:
        def fls_predictions(self, sentences: list[str]) -> FLSResult:
            return FLSResult(
                predictions=tuple(
                    FLSPrediction(
                        keep=int(sentence.rsplit("id=", maxsplit=1)[1]) % 2 == 1,
                        confidence=0.8,
                    )
                    for sentence in sentences
                ),
                model_revision="test-revision",
            )

    sentences = [
        "short id=0",
        "very long guidance sentence repeated repeated repeated id=1",
        "medium length id=2",
        "extremely long management outlook sentence repeated repeated repeated repeated id=3",
        "tiny id=4",
        "long demand forecast sentence repeated repeated id=5",
        "brief id=6",
    ]
    classifier = _FLSClassifier(_FakeInference())

    filtered, stats = classifier.keep_forward_sentences_with_stats(sentences)

    assert stats.batches == 1
    assert filtered == [sentences[1], sentences[3], sentences[5]]


def test_fls_classifier_sentence_cache_reuses_predictions_across_calls() -> None:
    class _FakeInference:
        def __init__(self) -> None:
            self.calls = 0

        def fls_predictions(self, sentences: list[str]) -> FLSResult:
            self.calls += 1
            return FLSResult(
                predictions=tuple(
                    FLSPrediction(keep=True, confidence=0.9) for _sentence in sentences
                ),
                model_revision="test-revision",
            )

    inference = _FakeInference()
    classifier = _FLSClassifier(inference)
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
    assert inference.calls == 1


def test_fls_classifier_service_error_keeps_lexical_fallback() -> None:
    class _FailingInference:
        def fls_predictions(self, _sentences: list[str]) -> FLSResult:
            raise InferenceFailure(
                code=InferenceErrorCode.UNAVAILABLE,
                request_id="test-request",
                retryable=True,
            )

    classifier = _FLSClassifier(_FailingInference())
    sentences = [
        "Historical accounting discussion.",
        "Management expects higher revenue next year.",
    ]

    filtered, stats = classifier.keep_forward_sentences_with_stats(sentences)

    assert filtered == [sentences[1]]
    assert stats.cache_misses == 0


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
