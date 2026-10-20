"""Compatibility builder for root composition during entrypoint migration."""

from langgraph.graph.state import CompiledStateGraph

from src.agents.news.application.wiring import build_financial_news_subgraph

__all__ = ["build_financial_news_subgraph", "CompiledStateGraph"]
