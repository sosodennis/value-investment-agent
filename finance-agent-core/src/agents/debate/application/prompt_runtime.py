from __future__ import annotations

import hashlib
import json
import os

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from src.agents.debate.application.state_readers import get_last_message_from_role
from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)

MAX_CHAR_HISTORY = 32000
MAX_CHAR_REPORTS = 50000
LOG_LLM_PAYLOADS = os.getenv("LOG_LLM_PAYLOADS", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


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

    log_event(
        logger,
        event="debate_reports_truncated",
        message="debate reports truncated by max chars",
        fields={"original_chars": len(compressed), "max_chars": max_chars},
    )
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
    log_event(
        logger,
        event="debate_history_trimmed",
        message="debate history trimmed for token budget",
        fields={
            "total_messages": len(history),
            "total_chars": total_chars,
            "trimmed_messages": len(trimmed),
            "trimmed_chars": trimmed_chars,
            "max_chars": max_chars,
        },
    )
    return trimmed


def log_messages(
    messages: list[BaseMessage], agent_name: str, round_num: int = 0
) -> None:
    """Log prompt metadata by default; full prompt text is opt-in."""
    if not LOG_LLM_PAYLOADS:
        total_chars = sum(len(str(msg.content)) for msg in messages)
        log_event(
            logger,
            event="debate_prompt_metadata",
            message="debate prompt metadata",
            fields={
                "agent": agent_name,
                "round_num": round_num,
                "message_count": len(messages),
                "chars": total_chars,
            },
        )
        return

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
    log_event(
        logger,
        event="debate_prompt_payload",
        message="debate prompt payload",
        fields={"agent": agent_name, "round_num": round_num, "payload": formatted_msg},
    )


def log_llm_config(agent_name: str, round_num: int, llm: object) -> None:
    model = getattr(llm, "model_name", None) or getattr(llm, "model", None) or "unknown"
    temperature = getattr(llm, "temperature", None)
    timeout = getattr(llm, "timeout", None)
    log_event(
        logger,
        event="debate_llm_config",
        message="debate llm config",
        fields={
            "agent": agent_name,
            "round_num": round_num,
            "model": model,
            "temperature": temperature,
            "timeout": timeout,
        },
    )


def log_debate_context(
    agent_name: str,
    round_num: int,
    history: list[BaseMessage],
    my_last_arg: str,
    opponent_last_arg: str,
    judge_feedback: str,
) -> None:
    log_event(
        logger,
        event="debate_context_metrics",
        message="debate context metrics",
        fields={
            "agent": agent_name,
            "round_num": round_num,
            "history_messages": len(history),
            "my_last_arg_chars": len(my_last_arg or ""),
            "opponent_last_arg_chars": len(opponent_last_arg or ""),
            "judge_feedback_chars": len(judge_feedback or ""),
        },
    )


def log_llm_response(agent_name: str, round_num: int, response_text: str) -> None:
    log_event(
        logger,
        event="debate_llm_output_metadata",
        message="debate llm output metadata",
        fields={
            "agent": agent_name,
            "round_num": round_num,
            "chars": len(response_text),
            "hash": hash_text(response_text),
        },
    )
    if LOG_LLM_PAYLOADS:
        log_event(
            logger,
            event="debate_llm_output_payload",
            message="debate llm output payload",
            fields={
                "agent": agent_name,
                "round_num": round_num,
                "payload": response_text,
            },
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
