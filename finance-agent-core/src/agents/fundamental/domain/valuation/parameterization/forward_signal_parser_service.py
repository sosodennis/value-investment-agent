from __future__ import annotations

from ..policies.forward_signal_contracts import ForwardSignal
from ..policies.forward_signal_policy import parse_forward_signals


def parse_market_forward_signals(raw_signals: object) -> list[ForwardSignal]:
    """Normalize raw market payloads into validated forward-signal contracts."""

    return parse_forward_signals(raw_signals)


__all__ = ["parse_market_forward_signals"]
