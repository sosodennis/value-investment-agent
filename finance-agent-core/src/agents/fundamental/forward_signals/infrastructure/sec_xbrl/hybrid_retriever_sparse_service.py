from __future__ import annotations

import math
import re


def sparse_rank_many(*, queries: list[str], corpus: list[str]) -> list[list[int]]:
    if not queries:
        return []
    if not corpus:
        return [[] for _ in queries]
    try:
        from rank_bm25 import BM25Okapi

        tokenized_corpus = [tokenize(text) for text in corpus]
        bm25 = BM25Okapi(tokenized_corpus)
        rankings: list[list[int]] = []
        for query in queries:
            scores = bm25.get_scores(tokenize(query))
            ranked = sorted(
                range(len(scores)),
                key=lambda idx: float(scores[idx]),
                reverse=True,
            )
            rankings.append(ranked)
        return rankings
    except Exception:
        token_sets = [set(tokenize(sentence)) for sentence in corpus]
        rankings = []
        for query in queries:
            query_terms = set(tokenize(query))
            scored: list[tuple[int, float]] = []
            for idx, tokens in enumerate(token_sets):
                overlap = len(query_terms & tokens)
                denominator = math.sqrt(max(1, len(tokens)))
                score = float(overlap) / denominator
                scored.append((idx, score))
            scored.sort(key=lambda item: item[1], reverse=True)
            rankings.append([idx for idx, _score in scored])
        return rankings


def tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", text.lower())
