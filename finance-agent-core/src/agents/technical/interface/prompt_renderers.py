from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate


def build_interpretation_chat_prompt(
    *, system_prompt: str, user_prompt: str
) -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            ("human", user_prompt),
        ]
    )
