import os

from src.shared.llm.contracts import LLMProviderPort, ModelRoute

from ...config.llm_config import (
    DEFAULT_MODEL,
)
from .gateway import LiteLLMGatewayConfig, LiteLLMGatewayProvider

_gateway_provider: LiteLLMGatewayProvider | None = None


def _get_gateway_provider() -> LiteLLMGatewayProvider:
    global _gateway_provider
    if _gateway_provider is None:
        _gateway_provider = LiteLLMGatewayProvider(LiteLLMGatewayConfig.from_env())
    return _gateway_provider


def get_llm_provider() -> LLMProviderPort:
    """Return the shared project-owned provider backed by the internal gateway."""
    return _get_gateway_provider()


def get_default_model_route(model: str = DEFAULT_MODEL) -> ModelRoute:
    """Resolve the configured gateway alias and its default upstream model."""
    return ModelRoute(
        alias=os.getenv("LLM_MODEL_ALIAS", "openrouter-default"),
        candidates=(model,),
    )


async def close_llm_provider() -> None:
    """Close the process-shared gateway clients during application shutdown."""
    global _gateway_provider
    provider = _gateway_provider
    _gateway_provider = None
    if provider is not None:
        await provider.aclose()
