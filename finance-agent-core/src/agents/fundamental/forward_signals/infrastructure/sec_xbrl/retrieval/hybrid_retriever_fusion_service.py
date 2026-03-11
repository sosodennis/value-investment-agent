from __future__ import annotations

_RRF_K = 60


def rrf_fuse(*, corpus_size: int, rankings: list[list[int]]) -> list[int]:
    scores: dict[int, float] = dict.fromkeys(range(corpus_size), 0.0)
    for ranking in rankings:
        if not ranking:
            continue
        for rank_position, doc_idx in enumerate(ranking):
            scores[doc_idx] += 1.0 / float(_RRF_K + rank_position + 1)
    fused = sorted(scores.keys(), key=lambda idx: scores[idx], reverse=True)
    return fused
