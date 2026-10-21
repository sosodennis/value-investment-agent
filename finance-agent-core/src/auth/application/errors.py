class AuthError(RuntimeError):
    """Base class for safe authentication failures."""


class InvalidCredentialsError(AuthError):
    """Credentials or session token were not accepted."""


class RegistrationConflictError(AuthError):
    """The normalized email is already registered."""


class RateLimitExceeded(AuthError):
    """The request exceeded the endpoint rate limit."""
