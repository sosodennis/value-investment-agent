class AuthError(RuntimeError):
    """Base class for safe authentication failures."""


class InvalidCredentialsError(AuthError):
    """Credentials or session token were not accepted."""


class RegistrationConflictError(AuthError):
    """The normalized email is already registered."""


class InvalidOrganizationContextError(AuthError):
    """The active organization is missing or unavailable to the user."""


class OrganizationNotFoundError(AuthError):
    """The requested organization is unavailable to the authenticated actor."""


class MembershipNotFoundError(AuthError):
    """The requested organization membership is unavailable."""


class InvalidMembershipTransitionError(AuthError):
    """The requested membership status transition is not allowed."""


class MembershipInvariantError(AuthError):
    """A membership mutation would violate an organization invariant."""


class OrganizationMutationConflictError(AuthError):
    """The organization changed after the mutation authorization snapshot."""


class AuthorizationDeniedError(AuthError):
    """A stable organization authorization decision denied the operation."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RateLimitExceeded(AuthError):
    """The request exceeded the endpoint rate limit."""
