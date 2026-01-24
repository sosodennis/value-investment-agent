from langchain_core.messages import AIMessageChunk

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
        "metadata": {"langgraph_node": "debate:bull"},
        "data": {"chunk": AIMessageChunk(content="thought")},
    }
    adapted = adapt_langgraph_event(lg_event, "thread_1", 5)
    assert adapted is not None
    assert adapted.type == "content.delta"
    assert adapted.data["content"] == "thought"
    assert adapted.source == "debate"  # From node mapping
    assert adapted.seq_id == 5


def test_adapt_agent_status_start():
    lg_event = {
        "event": "on_chain_start",
        "metadata": {"langgraph_node": "fundamental_analysis"},
        "data": {},
    }
    adapted = adapt_langgraph_event(lg_event, "thread_1", 10)
    assert adapted is not None
    assert adapted.type == "agent.status"
    assert adapted.data["status"] == "running"
    assert adapted.source == "fundamental_analysis"


def test_adapt_state_update_news():
    lg_event = {
        "event": "on_chain_end",
        "metadata": {"langgraph_node": "aggregator_node"},
        "data": {
            "output": {
                "__event_data__": {"news_items": [{"id": "1", "title": "market up"}]}
            }
        },
    }
    adapted = adapt_langgraph_event(lg_event, "thread_1", 15)
    assert adapted is not None
    # aggregator_node logic now flattens the result
    assert adapted.type == "state.update"
    assert "news_items" in adapted.data
    assert adapted.data["news_items"][0]["title"] == "market up"


def test_create_interrupt():
    payload = {"type": "ticker_selection", "candidates": []}
    event = create_interrupt_event(payload, "thread_1", 20)
    assert event.type == "interrupt.request"
    assert event.data["type"] == "ticker_selection"
    assert event.source == "system.interrupt"
