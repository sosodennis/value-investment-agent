class NotificationError(RuntimeError):
    """Base class for notification domain failures."""


class NotificationNotFoundError(NotificationError):
    """The requested recipient-owned inbox item is unavailable."""


class NotificationPayloadError(NotificationError):
    """A notification payload violates the safe payload contract."""


class NotificationEventConflictError(NotificationError):
    """An event key was reused for a different notification event."""
