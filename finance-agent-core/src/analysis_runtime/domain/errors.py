from collections.abc import Mapping


class RuntimeErrorBase(Exception):
    """Base for errors that are safe to map at the HTTP boundary."""

    code = "runtime_error"


class ThreadNotFoundError(RuntimeErrorBase):
    code = "thread_not_found"


class RunNotFoundError(RuntimeErrorBase):
    code = "run_not_found"


class RetryNotAvailableError(RuntimeErrorBase):
    code = "retry_not_available"


class RetryAlreadyActiveError(RuntimeErrorBase):
    code = "retry_already_active"


class RetryIdempotencyConflictError(RuntimeErrorBase):
    code = "retry_idempotency_conflict"


class InvalidCheckpointError(RuntimeErrorBase):
    code = "invalid_checkpoint"


class InvalidRetryTransitionError(RuntimeErrorBase):
    code = "invalid_retry_transition"


class RunAlreadyActiveError(RuntimeErrorBase):
    code = "run_already_active"


class InteractionNotAvailableError(RuntimeErrorBase):
    code = "interaction_not_available"


class InvalidInteractionResponseError(RuntimeErrorBase):
    code = "invalid_interaction_response"


class InvalidRunnerInterruptError(RuntimeErrorBase):
    code = "invalid_runner_interrupt"

    def __init__(
        self, message: str, *, diagnostics: Mapping[str, object] | None = None
    ) -> None:
        self.diagnostics = dict(diagnostics or {})
        super().__init__(message)


class InvalidRunnerOutputError(RuntimeErrorBase):
    code = "invalid_runner_output"


class InvalidCursorError(RuntimeErrorBase):
    code = "invalid_cursor"


class ReplayGapError(RuntimeErrorBase):
    code = "replay_gap"

    def __init__(self, oldest_seq: int, requested_seq: int) -> None:
        self.oldest_seq = oldest_seq
        self.requested_seq = requested_seq
        super().__init__(f"events before sequence {oldest_seq} are unavailable")


class SubscriberOverloadedError(RuntimeErrorBase):
    code = "subscriber_overloaded"


class ActivityPersistenceError(RuntimeErrorBase):
    code = "activity_persistence_failed"
