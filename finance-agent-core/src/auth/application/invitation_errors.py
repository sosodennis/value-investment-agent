from __future__ import annotations

from src.auth.application.errors import AuthError


class InvitationNotFoundError(AuthError):
    """The invitation is not visible to the authenticated actor."""


class InvitationConflictError(AuthError):
    """The requested invitation operation cannot be applied."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class InvitationMutationConflictError(InvitationConflictError):
    """A concurrent invitation or membership mutation won the race."""


class InvitationValidationError(AuthError):
    """The invitation request violates a domain invariant."""
