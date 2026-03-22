from langchain_core.messages import AIMessageChunk
from pydantic import BaseModel

from src.interface.events.adapters import adapt_langgraph_event, create_interrupt_event
from src.interface.events.protocol import PROTOCOL_VERSION, AgentEvent


def test_agent_event_serialization():
    event = AgentEvent(
        thread_id="test_thread",
        seq_id=1,
        type="content.delta",
        source="TestAgent",
        data={"content": "hello"},
    )
    json_str = event.model_dump_json()
    assert "test_thread" in json_str
    assert "content.delta" in json_str
    assert "TestAgent" in json_str
    assert event.model_dump()["protocol_version"] == PROTOCOL_VERSION


def test_adapt_token_stream():
    lg_event = {
        "event": "on_chat_model_stream",
        "metadata": {"langgraph_node": "r1_bull", "agent_id": "debate"},
        "data": {"chunk": AIMessageChunk(content="thought")},
    }
    adapted = adapt_langgraph_event(lg_event, "thread_1", 5)
    assert adapted and isinstance(adapted, list)
    event = adapted[0]
    assert event.type == "content.delta"
    assert event.data["content"] == "thought"
    assert event.source == "debate"  # From node mapping
    assert event.seq_id == 5


def test_adapt_agent_status_start():
    lg_event = {
        "event": "on_chain_start",
        "metadata": {
            "langgraph_node": "fundamental_agent",
            "agent_id": "fundamental_analysis",
            "agent_scope": "agent",
            "agent_node": "fundamental_agent",
        },
        "data": {},
    }
    adapted = adapt_langgraph_event(lg_event, "thread_1", 10)
    assert adapted and isinstance(adapted, list)
    assert adapted[0].type == "agent.status"
    assert adapted[0].data["status"] == "running"
    assert adapted[0].source == "fundamental_analysis"
    assert adapted[1].type == "agent.lifecycle"
    assert adapted[1].data["status"] == "running"
    assert adapted[1].source == "fundamental_analysis"


def test_adapt_state_update_news():
    lg_event = {
        "event": "on_chain_end",
        "metadata": {
            "langgraph_node": "aggregator_node",
            "agent_id": "financial_news_research",
        },
        "data": {
            "output": {
                "financial_news_research": {
                    "artifact": {
                        "kind": "financial_news_research.output",
                        "version": "v1",
                        "summary": "news complete",
                        "preview": {"top_headlines": ["market up"]},
                        "reference": None,
                    }
                }
            }
        },
    }
    adapted = adapt_langgraph_event(lg_event, "thread_1", 15)
    assert adapted and isinstance(adapted, list)
    event = adapted[0]
    # aggregator_node logic now flattens the result
    assert event.type == "state.update"
    assert event.data["kind"] == "financial_news_research.output"
    assert event.data["summary"] == "news complete"
    assert event.data["preview"]["top_headlines"][0] == "market up"
    status_events = [evt for evt in adapted if evt.type == "agent.status"]
    assert status_events
    assert status_events[-1].data["status"] == "done"


def test_adapt_state_update_emits_agent_lifecycle() -> None:
    lg_event = {
        "event": "on_chain_end",
        "metadata": {
            "langgraph_node": "news_agent",
            "agent_id": "financial_news_research",
            "agent_scope": "agent",
            "agent_node": "news_agent",
        },
        "data": {"output": {}},
    }

    adapted = adapt_langgraph_event(lg_event, "thread_1", 18)
    assert adapted and isinstance(adapted, list)
    lifecycle_events = [evt for evt in adapted if evt.type == "agent.lifecycle"]
    assert lifecycle_events
    assert lifecycle_events[0].source == "financial_news_research"
    assert lifecycle_events[0].data["status"] == "done"


def test_adapt_state_update_internal_node_skips_lifecycle() -> None:
    lg_event = {
        "event": "on_chain_end",
        "metadata": {
            "langgraph_node": "aggregator_node",
            "agent_id": "financial_news_research",
            "agent_scope": "agent",
            "agent_node": "news_agent",
        },
        "data": {"output": {}},
    }

    adapted = adapt_langgraph_event(lg_event, "thread_1", 19)
    lifecycle_events = [evt for evt in adapted if evt.type == "agent.lifecycle"]
    assert lifecycle_events == []


def test_create_interrupt():
    payload = {"type": "ticker_selection", "candidates": []}
    event = create_interrupt_event(payload, "thread_1", 20)
    assert event.type == "interrupt.request"
    assert event.data["type"] == "ticker_selection"
    assert event.source == "system.interrupt"
    schema = event.data["schema"]
    selected_symbol = schema["properties"]["selected_symbol"]
    assert selected_symbol["oneOf"] == []
    assert "enumNames" not in selected_symbol


def test_adapt_chain_error_emits_agent_status() -> None:
    lg_event = {
        "event": "on_chain_error",
        "metadata": {
            "langgraph_node": "clarifying",
            "agent_id": "intent_extraction",
        },
        "data": {"error": "boom"},
    }

    adapted = adapt_langgraph_event(lg_event, "thread_1", 40)
    assert adapted and isinstance(adapted, list)
    error_events = [evt for evt in adapted if evt.type == "error"]
    status_events = [evt for evt in adapted if evt.type == "agent.status"]
    assert error_events
    assert status_events
    assert status_events[0].data["status"] == "error"


def test_adapt_state_update_from_basemodel_output():
    class MockOutput(BaseModel):
        artifact: dict[str, object]

    lg_event = {
        "event": "on_chain_end",
        "metadata": {
            "langgraph_node": "intent_extraction",
            "agent_id": "intent_extraction",
        },
        "data": {
            "output": MockOutput(
                artifact={
                    "kind": "intent_extraction.output",
                    "version": "v1",
                    "summary": "Resolved ticker",
                    "preview": {"resolved_ticker": "GME"},
                    "reference": None,
                }
            )
        },
    }

    adapted = adapt_langgraph_event(lg_event, "thread_1", 30)
    assert adapted and isinstance(adapted, list)
    assert adapted[0].type == "state.update"
    assert adapted[0].source == "intent_extraction"
    assert adapted[0].data["preview"]["resolved_ticker"] == "GME"
    status_events = [evt for evt in adapted if evt.type == "agent.status"]
    assert status_events
    assert status_events[-1].data["status"] == "done"
