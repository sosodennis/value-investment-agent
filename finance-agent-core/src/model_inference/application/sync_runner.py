from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from threading import BoundedSemaphore, Lock
from typing import TypeVar

from src.model_inference.domain.errors import InferenceErrorCode, InferenceFailure

_ResultT = TypeVar("_ResultT")


class BoundedSyncRunner:
    def __init__(
        self,
        *,
        max_workers: int,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._capacity = BoundedSemaphore(max_workers)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="model-inference-sync",
        )
        self._lifecycle_lock = Lock()
        self._closed = False

    def run(
        self,
        *,
        request_id: str,
        deadline: float,
        work: Callable[[], _ResultT],
    ) -> _ResultT:
        if deadline <= time.monotonic():
            raise self._deadline_failure(request_id)
        if not self._capacity.acquire(blocking=False):
            raise self._overload_failure(request_id)

        with self._lifecycle_lock:
            if self._closed:
                self._capacity.release()
                raise self._unavailable_failure(request_id)
            try:
                future = self._executor.submit(work)
            except BaseException:
                self._capacity.release()
                raise

        future.add_done_callback(self._release_capacity)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            future.cancel()
            raise self._deadline_failure(request_id)
        completed, _ = wait((future,), timeout=remaining)
        if not completed:
            future.cancel()
            raise self._deadline_failure(request_id)
        result = future.result()
        if time.monotonic() >= deadline:
            raise self._deadline_failure(request_id)
        return result

    def close(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            self._executor.shutdown(wait=False)

    def _release_capacity(self, _future: Future[_ResultT]) -> None:
        self._capacity.release()

    @staticmethod
    def _deadline_failure(request_id: str) -> InferenceFailure:
        return InferenceFailure(
            code=InferenceErrorCode.DEADLINE_EXCEEDED,
            request_id=request_id,
            retryable=False,
            message="model inference deadline exceeded",
        )

    @staticmethod
    def _overload_failure(request_id: str) -> InferenceFailure:
        return InferenceFailure(
            code=InferenceErrorCode.OVERLOADED,
            request_id=request_id,
            retryable=False,
            message="synchronous model inference capacity is full",
        )

    @staticmethod
    def _unavailable_failure(request_id: str) -> InferenceFailure:
        return InferenceFailure(
            code=InferenceErrorCode.UNAVAILABLE,
            request_id=request_id,
            retryable=False,
            message="synchronous model inference runner is closed",
        )
