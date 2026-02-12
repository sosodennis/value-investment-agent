from langchain_core.messages import AIMessageChunk
from pydantic import BaseModel

from src.interface.adapters import adapt_langgraph_event, create_interrupt_event
from src.interface.protocol import AgentEvent


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
            "langgraph_node": "fundamental_analysis",
            "agent_id": "fundamental_analysis",
        },
        "data": {},
    }
    adapted = adapt_langgraph_event(lg_event, "thread_1", 10)
    assert adapted and isinstance(adapted, list)
    event = adapted[0]
    assert event.type == "agent.status"
    assert event.data["status"] == "running"
    assert event.source == "fundamental_analysis"


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
                    "artifact": {"news_items": [{"id": "1", "title": "market up"}]}
                }
            }
        },
    }
    adapted = adapt_langgraph_event(lg_event, "thread_1", 15)
    assert adapted and isinstance(adapted, list)
    event = adapted[0]
    # aggregator_node logic now flattens the result
    assert event.type == "state.update"
    assert "news_items" in event.data
    assert event.data["news_items"][0]["title"] == "market up"


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
