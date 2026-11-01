from __future__ import annotations

from fastapi import Depends, Request

from src.auth.domain.authorization import AuthorizationResource, OrganizationPermission
from src.auth.domain.entities import AuthenticatedContext
from src.auth.interface.dependencies import require_organization_permission


def _organization_resource(
    request: Request, _context: AuthenticatedContext
) -> AuthorizationResource:
    return AuthorizationResource(organization_id=request.path_params["organization_id"])


current_audit_reader = Depends(
    require_organization_permission(
        OrganizationPermission.ORGANIZATION_AUDIT_READ,
        resource_factory=_organization_resource,
    )
)
