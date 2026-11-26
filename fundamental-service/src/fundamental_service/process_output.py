"""Complete byte output for subprocess protocols, including unbuffered pipes."""

import io
import os
import select
import sys
from collections.abc import Callable
from contextlib import ExitStack


def write_stdout(
    raw: bytes, *, remaining_budget: Callable[[], float] | None = None
) -> None:
    if remaining_budget is not None:
        try:
            descriptor = sys.stdout.fileno()
        except (AttributeError, io.UnsupportedOperation):
            _write_buffered_stdout(raw, remaining_budget=remaining_budget)
        else:
            _write_descriptor_stdout(raw, descriptor, remaining_budget)
        return
    _write_buffered_stdout(raw)


def _write_buffered_stdout(
    raw: bytes, *, remaining_budget: Callable[[], float] | None = None
) -> None:
    remaining = memoryview(raw)
    while remaining:
        if remaining_budget is not None:
            remaining_budget()
        written = sys.stdout.buffer.write(remaining)
        if written is None or written <= 0:
            raise OSError("stdout write made no progress")
        remaining = remaining[written:]
    if remaining_budget is not None:
        remaining_budget()
    sys.stdout.buffer.flush()
    if remaining_budget is not None:
        remaining_budget()


def _wait_writable(descriptor: int, remaining_budget: Callable[[], float]) -> None:
    while True:
        if select.select([], [descriptor], [], remaining_budget())[1]:
            return


def _write_descriptor_stdout(
    raw: bytes, descriptor: int, remaining_budget: Callable[[], float]
) -> None:
    with ExitStack() as resources:
        saved = os.dup(descriptor)
        resources.callback(os.close, saved)
        discard = os.open(os.devnull, os.O_WRONLY)
        resources.callback(os.close, discard)
        blocking = os.get_blocking(descriptor)
        inheritable = os.get_inheritable(descriptor)
        os.set_blocking(descriptor, False)
        try:
            while True:
                remaining_budget()
                try:
                    sys.stdout.flush()
                    break
                except BlockingIOError:
                    _wait_writable(descriptor, remaining_budget)
            remaining = memoryview(raw)
            while remaining:
                remaining_budget()
                try:
                    written = os.write(descriptor, remaining)
                except BlockingIOError:
                    _wait_writable(descriptor, remaining_budget)
                    continue
                if written <= 0:
                    raise OSError("stdout write made no progress")
                remaining = remaining[written:]
            remaining_budget()
        except BaseException:
            os.dup2(discard, descriptor, inheritable=inheritable)
            try:
                sys.stdout.flush()
            finally:
                os.dup2(saved, descriptor, inheritable=inheritable)
            raise
        finally:
            os.set_blocking(descriptor, blocking)
