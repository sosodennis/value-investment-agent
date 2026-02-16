from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate


def build_search_extraction_chat_prompt(*, system_prompt: str) -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            ("user", "User Query: {query}\n\nSearch Results: {search_results}"),
        ]
    )


def build_intent_extraction_chat_prompt(*, system_prompt: str) -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            ("user", "{query}"),
        ]
    )
