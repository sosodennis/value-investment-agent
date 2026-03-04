from __future__ import annotations

from src.agents.intent.application.factory import build_intent_orchestrator
from src.agents.intent.application.orchestrator import IntentOrchestrator
from src.agents.intent.application.ports import IntentRuntimePorts
from src.agents.intent.infrastructure.market_data.company_profile_provider import (
    get_company_profile,
)
from src.agents.intent.infrastructure.market_data.yahoo_ticker_search_provider import (
    search_ticker,
)
from src.agents.intent.infrastructure.search.ddg_web_search_provider import web_search
from src.infrastructure.llm.provider import get_llm


def build_default_intent_orchestrator() -> IntentOrchestrator:
    runtime_ports = IntentRuntimePorts(
        llm_provider=lambda timeout: get_llm(timeout=timeout),
        search_ticker=search_ticker,
        web_search=web_search,
        company_profile=get_company_profile,
    )
    return build_intent_orchestrator(
        runtime_ports=runtime_ports,
    )


_intent_orchestrator: IntentOrchestrator | None = None


def get_intent_orchestrator() -> IntentOrchestrator:
    global _intent_orchestrator
    if _intent_orchestrator is None:
        _intent_orchestrator = build_default_intent_orchestrator()
    return _intent_orchestrator
