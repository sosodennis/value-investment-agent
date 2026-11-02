from __future__ import annotations

from src.agents.debate.application.state_readers import (
    resolved_ticker_from_state as debate_ticker,
)
from src.agents.fundamental.application.workflow_orchestrator.state_readers import (
    read_intent_state,
)
from src.agents.news.application.state_readers import (
    intent_context_from_state as news_context,
)
from src.agents.news.application.state_readers import (
    resolved_ticker_from_state as news_ticker,
)
from src.agents.technical.application.state_readers import (
    resolved_ticker_from_state as technical_ticker,
)
from src.shared.cross_agent.domain.market_identity import CompanyProfile


def test_agent_readers_use_shared_company_profile_transport() -> None:
    profile = CompanyProfile(ticker="AAPL", name="Apple Inc.")
    state = {"company_profile": profile}

    assert read_intent_state(state).resolved_ticker == "AAPL"
    assert news_ticker(state) == "AAPL"
    assert news_context(state)["company_profile"]["name"] == "Apple Inc."
    assert technical_ticker(state) == "AAPL"
    assert debate_ticker(state) == "AAPL"


def test_agent_readers_do_not_consume_the_removed_root_intent_context() -> None:
    legacy_state = {"intent_extraction": {"resolved_ticker": "AAPL"}}

    assert read_intent_state(legacy_state).resolved_ticker is None
    assert news_ticker(legacy_state) is None
    assert technical_ticker(legacy_state) is None
    assert debate_ticker(legacy_state) is None
