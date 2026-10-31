"""Default dependency assembly for the authentication capability."""

from __future__ import annotations

import os

from src.auth.application.authorization_service import AuthorizationService
from src.auth.application.directory_service import DirectoryService
from src.auth.application.organization_service import OrganizationService
from src.auth.application.ownership_service import OwnershipService
from src.auth.application.service import AuthService
from src.auth.infrastructure.directory_repository import SqlAlchemyDirectoryRepository
from src.auth.infrastructure.organization_repository import (
    SqlAlchemyOrganizationLifecycleRepository,
)
from src.auth.infrastructure.passwords import Argon2PasswordHasher
from src.auth.infrastructure.repositories import (
    SqlAlchemyOrganizationRepository,
    SqlAlchemyOwnershipRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
)

_auth_service: AuthService | None = None
_authorization_service: AuthorizationService | None = None
_organization_service: OrganizationService | None = None
_ownership_service: OwnershipService | None = None
_directory_service: DirectoryService | None = None


def _directory_cursor_secret() -> str:
    configured = os.getenv("DIRECTORY_CURSOR_SECRET", "").strip()
    if configured:
        return configured
    environment = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "production")).lower()
    if environment in {"development", "dev", "test"}:
        return "local-development-only-directory-cursor-secret"
    raise RuntimeError("DIRECTORY_CURSOR_SECRET is required")


def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService(
            users=SqlAlchemyUserRepository(),
            organizations=SqlAlchemyOrganizationRepository(),
            sessions=SqlAlchemySessionRepository(),
            password_hasher=Argon2PasswordHasher(),
        )
    return _auth_service


def get_ownership_service() -> OwnershipService:
    global _ownership_service
    if _ownership_service is None:
        _ownership_service = OwnershipService(SqlAlchemyOwnershipRepository())
    return _ownership_service


def get_authorization_service() -> AuthorizationService:
    global _authorization_service
    if _authorization_service is None:
        _authorization_service = AuthorizationService()
    return _authorization_service


def get_organization_service() -> OrganizationService:
    global _organization_service
    if _organization_service is None:
        repository = SqlAlchemyOrganizationLifecycleRepository()
        _organization_service = OrganizationService(
            repository=repository,
            authorization=get_authorization_service(),
        )
    return _organization_service


def get_directory_service() -> DirectoryService:
    global _directory_service
    if _directory_service is None:
        _directory_service = DirectoryService(
            repository=SqlAlchemyDirectoryRepository(),
            cursor_secret=_directory_cursor_secret(),
        )
    return _directory_service


def reset_auth_wiring() -> None:
    global \
        _auth_service, \
        _authorization_service, \
        _organization_service, \
        _ownership_service, \
        _directory_service
    _auth_service = None
    _authorization_service = None
    _organization_service = None
    _ownership_service = None
    _directory_service = None
