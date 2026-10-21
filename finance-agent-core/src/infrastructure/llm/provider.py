from src.shared.llm.contracts import LLMProviderPort, ModelRoute
from src.shared.llm.routes import DEFAULT_MODEL_ALIAS

from .gateway import LiteLLMGatewayConfig, LiteLLMGatewayProvider

MODEL_ROUTE_ALIAS = DEFAULT_MODEL_ALIAS
_gateway_provider: LiteLLMGatewayProvider | None = None


def _get_gateway_provider() -> LiteLLMGatewayProvider:
    global _gateway_provider
    if _gateway_provider is None:
        _gateway_provider = LiteLLMGatewayProvider(LiteLLMGatewayConfig.from_env())
    return _gateway_provider


def get_llm_provider() -> LLMProviderPort:
    """Return the shared project-owned provider backed by the internal gateway."""
    return _get_gateway_provider()


def get_default_model_route() -> ModelRoute:
    """Return the only application data-plane route.

    OpenRouter model selection belongs to the protected settings control plane
    and LiteLLM deployment projection. No agent or request may supply it here.
    """
    return ModelRoute(alias=MODEL_ROUTE_ALIAS)


async def close_llm_provider() -> None:
    """Close the process-shared gateway clients during application shutdown."""
    global _gateway_provider
    provider = _gateway_provider
    _gateway_provider = None
    if provider is not None:
        await provider.aclose()
