"""Compatibility import for root composition during entrypoint migration."""

from src.agents.fundamental.application.wiring import build_fundamental_subgraph

__all__ = ["build_fundamental_subgraph"]
