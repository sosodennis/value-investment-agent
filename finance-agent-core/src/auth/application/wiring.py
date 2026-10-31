"""Default dependency assembly for the authentication capability."""

from __future__ import annotations

from src.auth.application.authorization_service import AuthorizationService
from src.auth.application.ownership_service import OwnershipService
from src.auth.application.service import AuthService
from src.auth.infrastructure.passwords import Argon2PasswordHasher
from src.auth.infrastructure.repositories import (
    SqlAlchemyOrganizationRepository,
    SqlAlchemyOwnershipRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
)

_auth_service: AuthService | None = None
_authorization_service: AuthorizationService | None = None
_ownership_service: OwnershipService | None = None


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


def reset_auth_wiring() -> None:
    global _auth_service, _authorization_service, _ownership_service
    _auth_service = None
    _authorization_service = None
    _ownership_service = None
