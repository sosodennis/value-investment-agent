from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.shared.kernel.traceable import TraceableField

from ....policies.manual_assumption_policy import DEFAULT_TERMINAL_GROWTH, assume_rate
from ..shared.capm_market_defaults_service import resolve_capm_market_defaults

DEFAULT_BANK_RISK_FREE_RATE = 0.042
DEFAULT_BANK_BETA = 1.0


@dataclass(frozen=True)
class BankCapmTerminalInputs:
    risk_free_rate: float
    beta: float
    market_risk_premium: float
    terminal_growth_tf: TraceableField[float]


def build_bank_capm_terminal_inputs(
    *,
    market_snapshot: Mapping[str, object] | None,
    market_float: Callable[[Mapping[str, object] | None, str], float | None],
    default_market_risk_premium: float,
    assumptions: list[str],
) -> BankCapmTerminalInputs:
    market_defaults = resolve_capm_market_defaults(
        market_snapshot=market_snapshot,
        market_float=market_float,
        default_risk_free_rate=DEFAULT_BANK_RISK_FREE_RATE,
        risk_free_format=".1%",
        default_beta=DEFAULT_BANK_BETA,
        beta_format=".1f",
        default_market_risk_premium=default_market_risk_premium,
        market_risk_premium_format=".2%",
        assumptions=assumptions,
    )

    terminal_growth_tf = assume_rate(
        "Terminal Growth",
        DEFAULT_TERMINAL_GROWTH,
        "Policy default terminal growth (preview only; requires analyst review)",
    )
    assumptions.append(f"terminal_growth defaulted to {DEFAULT_TERMINAL_GROWTH:.2%}")

    return BankCapmTerminalInputs(
        risk_free_rate=market_defaults.risk_free_rate,
        beta=market_defaults.beta,
        market_risk_premium=market_defaults.market_risk_premium,
        terminal_growth_tf=terminal_growth_tf,
    )
