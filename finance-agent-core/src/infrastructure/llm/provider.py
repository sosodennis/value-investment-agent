import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from src.shared.llm.contracts import ModelRoute

from ...config.llm_config import (
    DEFAULT_MODEL,
    LLM_TIMEOUT,
    OPENROUTER_BASE_URL,
)
from .gateway import LiteLLMGatewayConfig, LiteLLMGatewayProvider
from .langchain_adapter import LangChainGatewayModelAdapter

_gateway_provider: LiteLLMGatewayProvider | None = None


def _get_gateway_provider() -> LiteLLMGatewayProvider:
    global _gateway_provider
    if _gateway_provider is None:
        _gateway_provider = LiteLLMGatewayProvider(LiteLLMGatewayConfig.from_env())
    return _gateway_provider


def get_llm(
    model: str = DEFAULT_MODEL, temperature: float = 0, timeout: float = LLM_TIMEOUT
) -> BaseChatModel:
    """
    Return the LangChain compatibility model used during agent migration.

    Production containers set ``LLM_GATEWAY_BASE_URL`` and therefore use the
    project-owned contract through LiteLLM. Direct OpenRouter remains only for
    local compatibility until all callers have moved to typed requests.
    """
    if os.getenv("LLM_GATEWAY_BASE_URL"):
        return LangChainGatewayModelAdapter(
            provider=_get_gateway_provider(),
            route=ModelRoute(
                alias=os.getenv("LLM_MODEL_ALIAS", "openrouter-default"),
                candidates=(model,),
            ),
            temperature=temperature,
            timeout_seconds=timeout,
        )

    or_key = os.getenv("OPENROUTER_API_KEY")
    if not or_key:
        raise RuntimeError(
            "LLM gateway is not configured and OPENROUTER_API_KEY is missing"
        )
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        base_url=OPENROUTER_BASE_URL,
        api_key=or_key,
        timeout=timeout,
        max_retries=0,
    )


async def close_llm_provider() -> None:
    """Close the process-shared gateway clients during application shutdown."""
    global _gateway_provider
    provider = _gateway_provider
    _gateway_provider = None
    if provider is not None:
        await provider.aclose()
