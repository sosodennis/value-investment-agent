from src.llm_provider.application.context import (
    get_provider_principal,
    reset_provider_principal,
    set_provider_principal,
)
from src.llm_provider.application.settings_service import ProviderSettingsService
from src.llm_provider.application.wiring import (
    close_llm_provider,
    get_default_model_route,
    get_llm_provider,
    get_provider_settings_service,
)
from src.llm_provider.composition.routes import (
    llm_settings_router,
    provider_keys_router,
)
from src.llm_provider.domain.contracts import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    CompletionResult,
    LLMAttempt,
    LLMAttribution,
    LLMErrorCode,
    LLMProviderError,
    LLMProviderPort,
    LLMRequestClass,
    LLMRouteResolver,
    ModelRoute,
    ProviderPrincipal,
    ResolvedModelRoute,
    StreamEvent,
    StructuredRequest,
    Usage,
)
from src.llm_provider.domain.errors import ProviderSettingsError
from src.llm_provider.domain.routes import DEFAULT_MODEL_ALIAS

MODEL_ROUTE_ALIAS = DEFAULT_MODEL_ALIAS


async def cleanup_expired_replacements() -> int:
    return await get_provider_settings_service().cleanup_expired_replacements()


async def synchronize_selected_model() -> None:
    await get_provider_settings_service().synchronize_selected_model()


__all__ = [
    "ChatMessage",
    "ChatRole",
    "CompletionRequest",
    "CompletionResult",
    "LLMAttempt",
    "LLMAttribution",
    "LLMErrorCode",
    "LLMProviderError",
    "LLMProviderPort",
    "ProviderSettingsError",
    "ProviderSettingsService",
    "LLMRequestClass",
    "LLMRouteResolver",
    "ModelRoute",
    "ProviderPrincipal",
    "ResolvedModelRoute",
    "StreamEvent",
    "StructuredRequest",
    "Usage",
    "close_llm_provider",
    "cleanup_expired_replacements",
    "get_default_model_route",
    "get_llm_provider",
    "get_provider_settings_service",
    "get_provider_principal",
    "reset_provider_principal",
    "set_provider_principal",
    "llm_settings_router",
    "provider_keys_router",
    "synchronize_selected_model",
]
