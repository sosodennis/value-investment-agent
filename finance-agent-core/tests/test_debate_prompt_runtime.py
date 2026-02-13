from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agents.debate.application.prompt_runtime import (
    build_bear_round_messages,
    build_bull_round_messages,
    build_moderator_messages,
    compress_reports,
)


def test_build_bull_round_messages_round_two_includes_feedback_and_attack():
    history = [
        AIMessage(content="old bull", name="GrowthHunter"),
        AIMessage(content="old bear", name="ForensicAccountant"),
        AIMessage(content="judge note", name="Judge"),
    ]

    messages, context = build_bull_round_messages(
        system_content="sys", round_num=2, history=history
    )

    assert len(messages) == 4
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], AIMessage)
    assert isinstance(messages[2], HumanMessage)
    assert isinstance(messages[3], HumanMessage)
    assert context == ("old bull", "old bear", "judge note")


def test_build_bear_round_messages_round_one_keeps_system_only():
    messages, context = build_bear_round_messages(
        system_content="sys", round_num=1, history=[]
    )
    assert len(messages) == 1
    assert isinstance(messages[0], SystemMessage)
    assert context is None


def test_build_moderator_messages_appends_instruction():
    history = [AIMessage(content="prior debate")]
    messages = build_moderator_messages(system_content="sys", history=history)
    assert isinstance(messages[0], SystemMessage)
    assert any(
        isinstance(msg, HumanMessage) and "Point out logical flaws" in str(msg.content)
        for msg in messages
    )


def test_compress_reports_truncates_when_over_limit() -> None:
    reports = {"financials": {"data": "x" * 200}}
    compressed = compress_reports(reports, max_chars=60)
    assert "[... TRUNCATED DUE TO TOKEN LIMITS ...]" in compressed
