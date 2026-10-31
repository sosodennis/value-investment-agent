from __future__ import annotations

from src.auth.application.errors import AuthorizationDeniedError
from src.auth.domain.authorization import (
    AuthorizationContext,
    AuthorizationResource,
    OrganizationAuthorizationPolicy,
    OrganizationPermission,
    PolicyDecision,
)


class AuthorizationService:
    def check(
        self,
        *,
        context: AuthorizationContext,
        permission: OrganizationPermission,
        resource: AuthorizationResource | None = None,
    ) -> PolicyDecision:
        return OrganizationAuthorizationPolicy.evaluate(
            context=context,
            permission=permission,
            resource=resource,
        )

    def require(
        self,
        *,
        context: AuthorizationContext,
        permission: OrganizationPermission,
        resource: AuthorizationResource | None = None,
    ) -> None:
        decision = self.check(
            context=context,
            permission=permission,
            resource=resource,
        )
        if not decision.allowed:
            assert decision.failure_code is not None
            raise AuthorizationDeniedError(decision.failure_code.value)
