from __future__ import annotations

from src.agents.fundamental.infrastructure.sec_xbrl.fls_filter import (
    filter_forward_looking_sentences,
    filter_forward_looking_sentences_with_stats,
)
from src.agents.fundamental.infrastructure.sec_xbrl.hybrid_retriever import (
    retrieve_relevant_sentences,
    retrieve_relevant_sentences_batch,
)
from src.agents.fundamental.infrastructure.sec_xbrl.sentence_pipeline import (
    split_text_into_sentences,
)


def test_split_text_into_sentences_handles_long_text() -> None:
    text = (
        "Management expects higher revenue for fiscal year 2027. "
        "The business reported historical operating metrics in the prior year. "
        "Guidance indicates margin expansion from operating leverage."
    )
    sentences = split_text_into_sentences(text, chunk_size=80, chunk_overlap=20)
    assert len(sentences) >= 2
    assert any("expects higher revenue" in sentence.lower() for sentence in sentences)


def test_split_text_into_sentences_splits_overlong_runon_sentence() -> None:
    text = (
        "Management expects higher revenue growth in 2027, and management expects "
        "higher recurring demand in enterprise accounts, and management expects "
        "operating leverage to improve gross margin as pricing actions normalize, "
        "while management also expects temporary cost inflation to moderate in the "
        "second half of the fiscal year, and management expects backlog conversion "
        "to improve with stronger execution across regions."
    )
    sentences = split_text_into_sentences(
        text,
        chunk_size=5000,
        chunk_overlap=0,
        max_sentence_chars=120,
    )
    assert len(sentences) >= 3
    assert all(len(sentence) <= 120 for sentence in sentences)
    assert any(
        "expects higher revenue growth" in sentence.lower() for sentence in sentences
    )


def test_filter_forward_looking_sentences_prefers_forward_language() -> None:
    sentences = [
        "During the prior year the company reported stable expenses.",
        "Management expects higher revenue and will improve margin next year.",
    ]
    filtered = filter_forward_looking_sentences(sentences)
    assert filtered
    assert any("expects higher revenue" in sentence.lower() for sentence in filtered)


def test_filter_forward_looking_sentences_with_stats_exposes_timing_fields() -> None:
    sentences = [
        "During the prior year the company reported stable expenses.",
        "Management expects higher revenue and will improve margin next year.",
    ]
    filtered, stats = filter_forward_looking_sentences_with_stats(sentences)
    assert filtered
    assert stats["model_load_ms"] >= 0.0
    assert stats["inference_ms"] >= 0.0
    assert stats["sentences_scored"] >= 0
    assert stats["prefilter_selected"] >= 0
    assert stats["batches"] >= 0
    assert stats["cache_hits"] >= 0
    assert stats["cache_misses"] >= 0


def test_retrieve_relevant_sentences_returns_metric_relevant_candidates() -> None:
    corpus = [
        "The company discussed a prior-year accounting adjustment.",
        "Management expects higher revenue growth and raised outlook for 2027.",
        "Operating margin pressure is expected due to temporary cost inflation.",
    ]
    results = retrieve_relevant_sentences(
        query="revenue growth outlook guidance",
        corpus=corpus,
        top_k=2,
    )
    assert results
    assert "revenue" in results[0].lower()


def test_retrieve_relevant_sentences_batch_returns_aligned_results() -> None:
    corpus = [
        "The company discussed a prior-year accounting adjustment.",
        "Management expects higher revenue growth and raised outlook for 2027.",
        "Operating margin pressure is expected due to temporary cost inflation.",
    ]
    results = retrieve_relevant_sentences_batch(
        queries=[
            "revenue growth outlook guidance",
            "operating margin pressure inflation",
        ],
        corpus=corpus,
        top_k=2,
    )
    assert len(results) == 2
    assert results[0]
    assert results[1]
    assert "revenue" in " ".join(results[0]).lower()
    assert "margin" in " ".join(results[1]).lower()
