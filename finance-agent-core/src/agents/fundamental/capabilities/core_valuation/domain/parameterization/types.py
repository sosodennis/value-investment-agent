from __future__ import annotations

from src.agents.fundamental.domain.shared.contracts.traceable import TraceableField

TraceInput = TraceableField[float] | TraceableField[list[float]]
MonteCarloControls = tuple[int, int | None, str]


__all__ = ["TraceInput", "MonteCarloControls"]
