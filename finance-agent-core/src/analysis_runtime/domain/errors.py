class RuntimeErrorBase(Exception):
    """Base for errors that are safe to map at the HTTP boundary."""

    code = "runtime_error"


class ThreadNotFoundError(RuntimeErrorBase):
    code = "thread_not_found"


class RunNotFoundError(RuntimeErrorBase):
    code = "run_not_found"


class RunAlreadyActiveError(RuntimeErrorBase):
    code = "run_already_active"


class InteractionNotAvailableError(RuntimeErrorBase):
    code = "interaction_not_available"


class InvalidInteractionResponseError(RuntimeErrorBase):
    code = "invalid_interaction_response"


class InvalidRunnerInterruptError(RuntimeErrorBase):
    code = "invalid_runner_interrupt"


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
