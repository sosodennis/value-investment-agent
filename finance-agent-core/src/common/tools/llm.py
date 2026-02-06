import os

from langchain_openai import ChatOpenAI

DEFAULT_MODEL = "arcee-ai/trinity-large-preview:free"


def get_llm(model: str = DEFAULT_MODEL, temperature: float = 0):
    """
    Standardize LLM configuration across all agents.
    """
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
        timeout=60,
        max_retries=2,
    )
