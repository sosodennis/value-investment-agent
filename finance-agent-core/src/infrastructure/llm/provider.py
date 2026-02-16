import os

from langchain_openai import ChatOpenAI

from ...config.llm_config import (
    DEFAULT_MODEL,
    LLM_MAX_RETRIES,
    LLM_TIMEOUT,
    OPENROUTER_BASE_URL,
)


def get_llm(
    model: str = DEFAULT_MODEL, temperature: float = 0, timeout: float = LLM_TIMEOUT
):
    """
    Standardize LLM configuration across all agents.
    If OPENROUTER_API_KEY is missing, falls back to default provider (OpenAI).
    """
    or_key = os.getenv("OPENROUTER_API_KEY")
    oa_key = os.getenv("OPENAI_API_KEY")

    if or_key:
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            base_url=OPENROUTER_BASE_URL,
            api_key=or_key,
            timeout=timeout,
            max_retries=LLM_MAX_RETRIES,
        )

    # Fallback to OpenAI
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=oa_key,
        timeout=timeout,
        max_retries=LLM_MAX_RETRIES,
    )
