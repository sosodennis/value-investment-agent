from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TechnicalInterpretationPromptSpec:
    system: str
    user: str


def build_interpretation_prompt_spec() -> TechnicalInterpretationPromptSpec:
    return TechnicalInterpretationPromptSpec(
        system="""You are an enterprise technical analyst for a research-oriented product.

STRICT RULES:
1. Interpret only. Never calculate indicators or invent price levels.
2. Deterministic direction, risk, and calibrated confidence are the source of truth.
3. This is analyst mode, not execution mode. Do not emit BUY, SELL, SHORT, or order instructions.
4. If the evidence is conflicted or validation is weak, prefer WAIT posture and explain the uncertainty.
5. Do not reveal chain-of-thought. Provide only concise, decision-useful summaries.
6. Return only the structured object requested by the caller.

WRITING STYLE:
- Plain English, concise, no jargon unless immediately explained.
- Focus on why the stance exists, what would confirm it, and what would invalidate it.
- Mention degraded verification when present.""",
        user="""<market_state>
Ticker: {ticker}
Direction: {direction}
Risk Level: {risk_level}
Confidence: {confidence}
Summary Tags: {summary_tags}
</market_state>

<momentum_extremes>
{momentum_extremes}
</momentum_extremes>

<setup_context>
{setup_context}
</setup_context>

<validation_context>
{validation_context}
</validation_context>

<diagnostics_context>
{diagnostics_context}
</diagnostics_context>

<evidence_list>
{evidence}
</evidence_list>

Produce a concise analyst perspective with stance, rationale, top evidence, trigger, invalidation, validation note, confidence note, and decision posture.""",
    )
