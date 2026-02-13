from __future__ import annotations

import hashlib
import json

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from src.agents.debate.application.state_readers import get_last_message_from_role
from src.common.tools.logger import get_logger

logger = get_logger(__name__)

MAX_CHAR_HISTORY = 32000
MAX_CHAR_REPORTS = 50000


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def compress_reports(
    reports: dict[str, object], max_chars: int = MAX_CHAR_REPORTS
) -> str:
    """Compress analyst reports to fit context window."""
    if not reports:
        return "{}"

    compressed = json.dumps(reports, indent=1, default=str)
    if len(compressed) <= max_chars:
        return compressed

    compressed = json.dumps(reports, separators=(",", ":"), default=str)
    if len(compressed) <= max_chars:
        return compressed

    logger.warning("⚠️ Truncating analyst reports: %d -> %d", len(compressed), max_chars)
    return compressed[:max_chars] + "\n\n[... TRUNCATED DUE TO TOKEN LIMITS ...]"


def get_trimmed_history(
    history: list[BaseMessage], max_chars: int = MAX_CHAR_HISTORY
) -> list[BaseMessage]:
    """Get the most recent messages that fit within the character budget."""
    if not history:
        return []

    trimmed: list[BaseMessage] = []
    current_chars = 0
    for msg in reversed(history):
        msg_content = str(msg.content)
        if current_chars + len(msg_content) > max_chars:
            break
        trimmed.insert(0, msg)
        current_chars += len(msg_content)

    total_chars = sum(len(str(msg.content)) for msg in history)
    trimmed_chars = sum(len(str(msg.content)) for msg in trimmed)
    logger.info(
        "DEBATE_HISTORY_TRIM total_messages=%d total_chars=%d trimmed_messages=%d trimmed_chars=%d max_chars=%d",
        len(history),
        total_chars,
        len(trimmed),
        trimmed_chars,
        max_chars,
    )
    return trimmed


def log_messages(
    messages: list[BaseMessage], agent_name: str, round_num: int = 0
) -> None:
    """Log full message content for audit/debugging."""
    log_header = f"PROMPT SENT TO {agent_name}"
    if round_num:
        log_header += f" (Round {round_num})"

    formatted_msg = "\n" + "=" * 50 + f"\n{log_header}\n" + "=" * 50 + "\n"
    for i, msg in enumerate(messages):
        role = (
            "System"
            if isinstance(msg, SystemMessage)
            else "Human"
            if isinstance(msg, HumanMessage)
            else "AI"
            if isinstance(msg, AIMessage)
            else "Unknown"
        )
        content = msg.content
        formatted_msg += f"[{i + 1}] {role} Message:\n{content}\n" + "-" * 30 + "\n"
    formatted_msg += "=" * 50
    logger.info(formatted_msg)


def log_llm_config(agent_name: str, round_num: int, llm: object) -> None:
    model = getattr(llm, "model_name", None) or getattr(llm, "model", None) or "unknown"
    temperature = getattr(llm, "temperature", None)
    timeout = getattr(llm, "timeout", None)
    logger.info(
        "DEBATE_LLM_CONFIG agent=%s round=%d model=%s temperature=%s timeout=%s",
        agent_name,
        round_num,
        model,
        temperature,
        timeout,
    )


def log_compressed_reports(
    stage: str, ticker: str | None, compressed_reports: str, source: str
) -> None:
    logger.info(
        "DEBATE_REPORTS stage=%s ticker=%s source=%s chars=%d hash=%s",
        stage,
        ticker or "unknown",
        source,
        len(compressed_reports),
        hash_text(compressed_reports),
    )


def log_debate_context(
    agent_name: str,
    round_num: int,
    history: list[BaseMessage],
    my_last_arg: str,
    opponent_last_arg: str,
    judge_feedback: str,
) -> None:
    logger.info(
        "DEBATE_CONTEXT agent=%s round=%d history_messages=%d my_last_arg_chars=%d opponent_last_arg_chars=%d judge_feedback_chars=%d",
        agent_name,
        round_num,
        len(history),
        len(my_last_arg or ""),
        len(opponent_last_arg or ""),
        len(judge_feedback or ""),
    )


def log_llm_response(agent_name: str, round_num: int, response_text: str) -> None:
    logger.info(
        "DEBATE_OUTPUT agent=%s round=%d chars=%d hash=%s",
        agent_name,
        round_num,
        len(response_text),
        hash_text(response_text),
    )
    logger.info(
        "DEBATE_OUTPUT_TEXT agent=%s round=%d\n%s",
        agent_name,
        round_num,
        response_text,
    )


def build_bull_round_messages(
    *,
    system_content: str,
    round_num: int,
    history: list[BaseMessage],
) -> tuple[list[BaseMessage], tuple[str, str, str] | None]:
    messages: list[BaseMessage] = [SystemMessage(content=system_content)]
    if round_num == 1:
        return messages, None

    my_last_arg = get_last_message_from_role(history, "GrowthHunter")
    opponent_last_arg = get_last_message_from_role(history, "ForensicAccountant")
    judge_feedback = get_last_message_from_role(history, "Judge")

    if my_last_arg:
        messages.append(AIMessage(content=f"(My Previous Argument):\n{my_last_arg}"))
    if judge_feedback:
        messages.append(
            HumanMessage(
                content=f"<moderator_feedback>\n{judge_feedback}\n</moderator_feedback>"
            )
        )
    if opponent_last_arg:
        messages.append(
            HumanMessage(content=f"DESTROY this argument:\n\n{opponent_last_arg}")
        )
    return messages, (my_last_arg, opponent_last_arg, judge_feedback)


def build_bear_round_messages(
    *,
    system_content: str,
    round_num: int,
    history: list[BaseMessage],
) -> tuple[list[BaseMessage], tuple[str, str, str] | None]:
    messages: list[BaseMessage] = [SystemMessage(content=system_content)]
    if round_num == 1:
        return messages, None

    my_last_arg = get_last_message_from_role(history, "ForensicAccountant")
    opponent_last_arg = get_last_message_from_role(history, "GrowthHunter")
    judge_feedback = get_last_message_from_role(history, "Judge")

    if my_last_arg:
        messages.append(AIMessage(content=f"(My Previous Argument):\n{my_last_arg}"))
    if judge_feedback:
        messages.append(
            HumanMessage(
                content=f"<moderator_feedback>\n{judge_feedback}\n</moderator_feedback>"
            )
        )
    if opponent_last_arg:
        messages.append(
            HumanMessage(content=f"DESTROY this argument:\n\n{opponent_last_arg}")
        )
    return messages, (my_last_arg, opponent_last_arg, judge_feedback)


def build_moderator_messages(
    *,
    system_content: str,
    history: list[BaseMessage],
) -> list[BaseMessage]:
    trimmed_history = get_trimmed_history(history)
    messages: list[BaseMessage] = [
        SystemMessage(content=system_content)
    ] + trimmed_history
    messages.append(HumanMessage(content="Point out logical flaws. DO NOT SUMMARIZE."))
    return messages
