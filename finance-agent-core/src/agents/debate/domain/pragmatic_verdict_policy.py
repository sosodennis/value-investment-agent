from __future__ import annotations

import logging
from collections.abc import Mapping
from enum import Enum
from typing import Protocol

from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject

logger = get_logger(__name__)


class RiskFreeRateProvider(Protocol):
    def __call__(self) -> float: ...


class DynamicPayoffMapProvider(Protocol):
    def __call__(self, ticker: str | None, risk_profile: str) -> dict[str, float]: ...


def calculate_pragmatic_verdict(
    conclusion_data: Mapping[str, object],
    *,
    ticker: str | None,
    get_risk_free_rate: RiskFreeRateProvider,
    get_payoff_map: DynamicPayoffMapProvider,
) -> JSONObject:
    scenarios_raw = conclusion_data.get("scenario_analysis")
    scenarios = scenarios_raw if isinstance(scenarios_raw, Mapping) else {}
    risk_profile_raw = conclusion_data.get("risk_profile")
    risk_profile = (
        str(risk_profile_raw) if isinstance(risk_profile_raw, str) else "GROWTH_TECH"
    )

    p_bull, p_bear, p_base = _get_normalized_probabilities(scenarios)

    payoff_map = get_payoff_map(ticker, risk_profile)
    r_bull = _get_return_from_scenario(scenarios, "bull_case", payoff_map)
    r_base = _get_return_from_scenario(scenarios, "base_case", payoff_map)
    r_bear = _get_return_from_scenario(scenarios, "bear_case", payoff_map)

    raw_ev = (p_bull * r_bull) + (p_base * r_base) + (p_bear * r_bear)

    risk_free = get_risk_free_rate()
    alpha = raw_ev - risk_free

    weighted_upside = (p_bull * r_bull) + (p_base * max(0, r_base))
    weighted_downside = (p_bear * abs(r_bear)) + (p_base * abs(min(0, r_base)))
    weighted_downside *= 1.5

    data_quality_issue = False
    if weighted_downside < 0.001:
        if abs(r_bear) < 0.01 and abs(r_base) < 0.01:
            data_quality_issue = True
            weighted_downside = 0.05
        else:
            rr_ratio = 10.0
    else:
        rr_ratio = weighted_upside / weighted_downside

    if data_quality_issue:
        rr_ratio = weighted_upside / weighted_downside
        direction = "NEUTRAL"
        bias = "UNCERTAIN"
        conviction = 30
        log_event(
            logger,
            event="debate_pragmatic_verdict_data_quality_issue",
            message="data quality issue detected; forcing neutral verdict",
            level=logging.WARNING,
            error_code="DEBATE_DATA_QUALITY_ISSUE",
            fields={"ticker": ticker, "r_bear": r_bear, "r_base": r_base},
        )
    else:
        direction = "NEUTRAL"
        bias = "FLAT"
        conviction = 50

        if rr_ratio > 2.0 and alpha > 0:
            direction = "STRONG_LONG"
            bias = "BULLISH"
            conviction = 90
        elif rr_ratio > 1.3 and alpha > 0:
            direction = "LONG"
            bias = "BULLISH"
            conviction = 70
        elif alpha < 0 and rr_ratio < 0.8:
            direction = "SHORT"
            bias = "BEARISH"
            conviction = 70
        elif alpha < 0:
            direction = "AVOID"
            bias = "BEARISH"

    return {
        "ticker": ticker,
        "final_verdict": direction,
        "analysis_bias": bias,
        "rr_ratio": round(rr_ratio, 2),
        "alpha": round(alpha, 4),
        "raw_ev": round(raw_ev, 4),
        "conviction": conviction,
        "model_summary": f"Reward/Risk: {rr_ratio:.2f}x, Alpha: {alpha:.2%}",
        "risk_free_benchmark": round(risk_free, 4),
        "data_quality_warning": data_quality_issue,
    }


def _parse_score(value: object) -> float:
    if isinstance(value, str):
        value = value.replace("%", "").strip()
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _get_normalized_probabilities(
    scenarios: Mapping[str, object],
) -> tuple[float, float, float]:
    s_bull = _parse_score(_scenario_field(scenarios, "bull_case", "probability"))
    s_bear = _parse_score(_scenario_field(scenarios, "bear_case", "probability"))
    s_base = _parse_score(_scenario_field(scenarios, "base_case", "probability"))

    total_score = s_bull + s_bear + s_base
    if total_score == 0:
        return 0.33, 0.33, 0.34
    return s_bull / total_score, s_bear / total_score, s_base / total_score


def _get_return_from_scenario(
    scenarios: Mapping[str, object],
    case_key: str,
    payoff_map: Mapping[str, float],
) -> float:
    implication = _scenario_field(scenarios, case_key, "price_implication") or "FLAT"
    if isinstance(implication, Enum):
        implication = implication.value
    implication_text = str(implication).upper()

    for key, value in payoff_map.items():
        if key in implication_text:
            return value
    return 0.0


def _scenario_field(
    scenarios: Mapping[str, object], case_key: str, field: str
) -> object | None:
    scenario_raw = scenarios.get(case_key)
    if not isinstance(scenario_raw, Mapping):
        return None
    return scenario_raw.get(field)
