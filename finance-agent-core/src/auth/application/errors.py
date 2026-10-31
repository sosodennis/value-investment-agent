class AuthError(RuntimeError):
    """Base class for safe authentication failures."""


class InvalidCredentialsError(AuthError):
    """Credentials or session token were not accepted."""


class RegistrationConflictError(AuthError):
    """The normalized email is already registered."""


class InvalidOrganizationContextError(AuthError):
    """The active organization is missing or unavailable to the user."""


class AuthorizationDeniedError(AuthError):
    """A stable organization authorization decision denied the operation."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RateLimitExceeded(AuthError):
    """The request exceeded the endpoint rate limit."""
