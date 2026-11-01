import re


class NotificationError(RuntimeError):
    """Base class for notification domain failures."""


class NotificationNotFoundError(NotificationError):
    """The requested recipient-owned inbox item is unavailable."""


class NotificationPayloadError(NotificationError):
    """A notification payload violates the safe payload contract."""


class NotificationEventConflictError(NotificationError):
    """An event key was reused for a different notification event."""


class NotificationDeliveryError(NotificationError):
    """A notification adapter failed to deliver an outbox item."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        safe_code: str = "adapter_delivery_failed",
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        normalized_code = safe_code.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.:-]{0,63}", normalized_code) or any(
            part in normalized_code
            for part in (
                "api",
                "authorization",
                "credential",
                "key",
                "password",
                "secret",
                "token",
            )
        ):
            normalized_code = "adapter_delivery_failed"
        self.safe_code = normalized_code


class NotificationOutboxLeaseError(NotificationError):
    """An outbox worker attempted to update a delivery it no longer owns."""
