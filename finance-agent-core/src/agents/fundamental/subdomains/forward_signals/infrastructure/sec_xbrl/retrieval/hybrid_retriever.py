from __future__ import annotations

import math
import re

from .hybrid_retriever_dense_service import _DenseRetriever

_DENSE_RETRIEVER = _DenseRetriever()
_RRF_K = 60


def _rrf_fuse(*, corpus_size: int, rankings: list[list[int]]) -> list[int]:
    scores: dict[int, float] = dict.fromkeys(range(corpus_size), 0.0)
    for ranking in rankings:
        if not ranking:
            continue
        for rank_position, doc_idx in enumerate(ranking):
            scores[doc_idx] += 1.0 / float(_RRF_K + rank_position + 1)
    fused = sorted(scores.keys(), key=lambda idx: scores[idx], reverse=True)
    return fused


def _sparse_rank_many(*, queries: list[str], corpus: list[str]) -> list[list[int]]:
    if not queries:
        return []
    if not corpus:
        return [[] for _ in queries]
    try:
        from rank_bm25 import BM25Okapi

        tokenized_corpus = [_tokenize(text) for text in corpus]
        bm25 = BM25Okapi(tokenized_corpus)
        rankings: list[list[int]] = []
        for query in queries:
            scores = bm25.get_scores(_tokenize(query))
            ranked = sorted(
                range(len(scores)),
                key=lambda idx: float(scores[idx]),
                reverse=True,
            )
            rankings.append(ranked)
        return rankings
    except Exception:
        token_sets = [set(_tokenize(sentence)) for sentence in corpus]
        rankings = []
        for query in queries:
            query_terms = set(_tokenize(query))
            scored: list[tuple[int, float]] = []
            for idx, tokens in enumerate(token_sets):
                overlap = len(query_terms & tokens)
                denominator = math.sqrt(max(1, len(tokens)))
                score = float(overlap) / denominator
                scored.append((idx, score))
            scored.sort(key=lambda item: item[1], reverse=True)
            rankings.append([idx for idx, _score in scored])
        return rankings


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", text.lower())


def retrieve_relevant_sentences(
    *,
    query: str,
    corpus: list[str],
    top_k: int = 24,
) -> list[str]:
    results = retrieve_relevant_sentences_batch(
        queries=[query],
        corpus=corpus,
        top_k=top_k,
    )
    if not results:
        return []
    return results[0]


def retrieve_relevant_sentences_batch(
    *,
    queries: list[str],
    corpus: list[str],
    top_k: int = 24,
) -> list[list[str]]:
    if not queries:
        return []
    if not corpus:
        return [[] for _ in queries]
    k = max(1, min(top_k, len(corpus)))
    sparse_rankings = _sparse_rank_many(queries=queries, corpus=corpus)
    dense_rankings = _DENSE_RETRIEVER.rank_many(queries=queries, corpus=corpus)
    merged_sentences: list[list[str]] = []
    for query_idx in range(len(queries)):
        sparse_ranking = (
            sparse_rankings[query_idx] if query_idx < len(sparse_rankings) else []
        )
        dense_ranking = (
            dense_rankings[query_idx] if query_idx < len(dense_rankings) else []
        )
        fused = _rrf_fuse(
            corpus_size=len(corpus),
            rankings=[sparse_ranking, dense_ranking],
        )
        selected_indices = fused[:k]
        merged_sentences.append([corpus[idx] for idx in selected_indices])
    return merged_sentences


__all__ = [
    "_DenseRetriever",
    "retrieve_relevant_sentences",
    "retrieve_relevant_sentences_batch",
]
