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
ORGANIZATION_ROUTE_PREFIX = "openrouter-org-"


def organization_route_alias(organization_id: str) -> str:
    """Return a stable opaque LiteLLM alias for one organization pool."""

    digest = sha256(organization_id.encode("utf-8")).hexdigest()[:20]
    return f"{ORGANIZATION_ROUTE_PREFIX}{digest}"


class OrganizationScopedRouteResolver(LLMRouteResolver):
    """Resolve the logical route into the active organization's gateway pool."""

    def resolve(
        self,
        *,
        route: ModelRoute,
        principal: ProviderPrincipal | None,
    ) -> ResolvedModelRoute:
        if route.alias != DEFAULT_MODEL_ALIAS:
            raise ValueError("unsupported provider route")
        if principal is None or principal.organization_id == "unscoped":
            raise ValueError("organization provider context is required")
        return ResolvedModelRoute(
            logical_alias=route.alias,
            gateway_alias=organization_route_alias(principal.organization_id),
        )


__all__ = [
    "DEFAULT_MODEL_ALIAS",
    "ORGANIZATION_ROUTE_PREFIX",
    "OrganizationScopedRouteResolver",
    "organization_route_alias",
]
