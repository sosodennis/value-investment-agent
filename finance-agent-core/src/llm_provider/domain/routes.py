"""Provider route identifiers shared by control and data planes."""

from __future__ import annotations

from hashlib import sha256

from .contracts import (
    LLMRouteResolver,
    ModelRoute,
    ProviderPrincipal,
    ResolvedModelRoute,
)

DEFAULT_MODEL_ALIAS = "openrouter-default"
USER_ROUTE_PREFIX = "openrouter-user-"


def user_route_alias(user_id: str) -> str:
    """Return a stable opaque LiteLLM alias for one authenticated user."""

    digest = sha256(user_id.encode("utf-8")).hexdigest()[:20]
    return f"{USER_ROUTE_PREFIX}{digest}"


class UserScopedRouteResolver(LLMRouteResolver):
    """Resolve the only logical route into a user-owned gateway pool."""

    def resolve(
        self,
        *,
        route: ModelRoute,
        principal: ProviderPrincipal | None,
    ) -> ResolvedModelRoute:
        if route.alias != DEFAULT_MODEL_ALIAS:
            raise ValueError("unsupported provider route")
        if principal is None:
            return ResolvedModelRoute(
                logical_alias=route.alias,
                gateway_alias=route.alias,
            )
        return ResolvedModelRoute(
            logical_alias=route.alias,
            gateway_alias=user_route_alias(principal.user_id),
        )


__all__ = [
    "DEFAULT_MODEL_ALIAS",
    "USER_ROUTE_PREFIX",
    "UserScopedRouteResolver",
    "user_route_alias",
]
