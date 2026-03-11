from __future__ import annotations

from .model_selection_contracts import ModelCandidate, SelectionSignals


def build_model_selection_reasoning(
    *,
    signals: SelectionSignals,
    ranked_candidates: tuple[ModelCandidate, ...],
) -> str:
    reasons: list[str] = [
        f"Sector/Industry: {signals.sector or 'unknown'} / {signals.industry or 'unknown'}"
    ]
    if signals.sic is not None:
        reasons.append(f"SIC: {signals.sic}")
    if signals.revenue_cagr is not None:
        reasons.append(f"Revenue CAGR: {signals.revenue_cagr:.1%}")
    if signals.is_profitable is not None:
        reasons.append(f"Profitable: {'Yes' if signals.is_profitable else 'No'}")

    candidate_lines: list[str] = []
    for candidate in ranked_candidates[:3]:
        missing = (
            f" (missing: {', '.join(candidate.missing_fields)})"
            if candidate.missing_fields
            else ""
        )
        candidate_lines.append(
            f"- {candidate.model.value}: score {candidate.score:.2f} | "
            f"{', '.join(candidate.reasons)}{missing}"
        )

    return "\n".join(
        ["Model selection signals:"]
        + [f"- {line}" for line in reasons]
        + candidate_lines
    )
