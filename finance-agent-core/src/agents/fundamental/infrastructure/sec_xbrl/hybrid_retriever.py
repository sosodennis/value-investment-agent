from __future__ import annotations

from .hybrid_retriever_dense_service import _DenseRetriever
from .hybrid_retriever_fusion_service import rrf_fuse
from .hybrid_retriever_sparse_service import sparse_rank_many

_DENSE_RETRIEVER = _DenseRetriever()


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
    sparse_rankings = sparse_rank_many(queries=queries, corpus=corpus)
    dense_rankings = _DENSE_RETRIEVER.rank_many(queries=queries, corpus=corpus)
    merged_sentences: list[list[str]] = []
    for query_idx in range(len(queries)):
        sparse_ranking = (
            sparse_rankings[query_idx] if query_idx < len(sparse_rankings) else []
        )
        dense_ranking = (
            dense_rankings[query_idx] if query_idx < len(dense_rankings) else []
        )
        fused = rrf_fuse(
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
