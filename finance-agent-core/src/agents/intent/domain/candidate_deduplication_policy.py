from __future__ import annotations

import re

from src.agents.intent.domain.ticker_candidate import TickerCandidate


def deduplicate_candidates(candidates: list[TickerCandidate]) -> list[TickerCandidate]:
    """
    De-duplicate ticker candidates that are likely the same security (e.g., BRK.B vs BRK-B).
    """
    seen_normalized: dict[str, TickerCandidate] = {}
    unique_candidates: list[TickerCandidate] = []

    for candidate in candidates:
        norm_symbol = re.sub(r"[\\.\\-]", "", candidate.symbol.upper())

        if norm_symbol not in seen_normalized:
            seen_normalized[norm_symbol] = candidate
            unique_candidates.append(candidate)
        else:
            if candidate.confidence > seen_normalized[norm_symbol].confidence:
                idx = unique_candidates.index(seen_normalized[norm_symbol])
                unique_candidates[idx] = candidate
                seen_normalized[norm_symbol] = candidate

    return unique_candidates
