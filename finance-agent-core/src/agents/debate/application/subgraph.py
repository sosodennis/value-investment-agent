"""Compatibility import for root composition until its entrypoint migration."""

from src.agents.debate.application.wiring import build_debate_subgraph

__all__ = ["build_debate_subgraph"]
