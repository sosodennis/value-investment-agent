from __future__ import annotations

from src.agents.intent.domain.models import TickerCandidate


def should_request_clarification(
    candidates: list[TickerCandidate], confidence_threshold: float = 0.85
) -> bool:
    if not candidates:
        return True

    if len(candidates) == 1 and candidates[0].confidence >= confidence_threshold:
        return False

    if len(candidates) > 1:
        if len(candidates) >= 2:
            top_conf = candidates[0].confidence
            second_conf = candidates[1].confidence
            if abs(top_conf - second_conf) <= 0.15:
                return True
        return True

    return False
