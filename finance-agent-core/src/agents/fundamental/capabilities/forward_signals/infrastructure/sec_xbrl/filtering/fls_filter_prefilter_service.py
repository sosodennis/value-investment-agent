from __future__ import annotations

import re

FORWARD_HINT_PATTERN = re.compile(
    r"\b(?:will|expects?|expecting|guidance|outlook|forecast|project(?:s|ed)?|"
    r"anticipat(?:e|es|ed)|target(?:s|ed)?)\b",
    re.IGNORECASE,
)


def prefilter_for_inference(
    sentences: list[str],
    *,
    max_sentences: int,
    context_window: int,
) -> list[str]:
    if not sentences:
        return []
    if len(sentences) <= max_sentences:
        return sentences

    anchor_indices = [
        idx
        for idx, sentence in enumerate(sentences)
        if FORWARD_HINT_PATTERN.search(sentence)
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
            key=lambda idx: forward_likelihood_score(sentences[idx]),
            reverse=True,
        )
        for idx in ranked_remaining:
            if len(selected_indices) >= max_sentences:
                break
            if forward_likelihood_score(sentences[idx]) <= 0:
                break
            selected_indices.add(idx)

    if len(selected_indices) > max_sentences:
        ranked_selected = sorted(
            selected_indices,
            key=lambda idx: (
                forward_likelihood_score(sentences[idx]),
                -idx,
            ),
            reverse=True,
        )
        selected_indices = set(ranked_selected[:max_sentences])

    ordered_indices = sorted(selected_indices)
    return [sentences[idx] for idx in ordered_indices]


def forward_likelihood_score(sentence: str) -> int:
    lowered = sentence.lower()
    score = 0
    if FORWARD_HINT_PATTERN.search(sentence):
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


def rule_based_filter(sentences: list[str]) -> list[str]:
    candidates = [
        sentence for sentence in sentences if FORWARD_HINT_PATTERN.search(sentence)
    ]
    return candidates if candidates else sentences
