"""Bounded file reads for complete scan-only resource hashes."""

from __future__ import annotations

import errno
import mmap
import os
import sys
from collections.abc import Callable
from pathlib import Path
from types import TracebackType

_BUFFER_BYTES = 1024 * 1024
_UNSUPPORTED_DIRECT = frozenset((errno.EINVAL, errno.EOPNOTSUPP, errno.ENOSYS))


class ResourceHashReader:
    """One scan's buffer; callback views are borrowed until the callback returns."""

    def __init__(self, *, direct: bool = True) -> None:
        self._direct = (
            getattr(os, "O_DIRECT", 0)
            if direct and sys.platform == "linux" and hasattr(os, "readv")
            else 0
        )
        self._buffer: mmap.mmap | None = None
        self._closed = False

    def __enter__(self) -> ResourceHashReader:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._buffer is not None:
            self._buffer.close()
            self._buffer = None
        self._closed = True

    def _read_buffer(self) -> mmap.mmap:
        if self._closed:
            raise RuntimeError("resource hash reader is closed")
        if self._buffer is None:
            # Anonymous shared memory avoids O_DIRECT/private-page fork races.
            # It is scoped RAM, fully charged to the existing worker's cgroup.
            self._buffer = mmap.mmap(-1, _BUFFER_BYTES)
        return self._buffer

    def update(self, path: Path, consume: Callable[[memoryview], None]) -> None:
        if self._closed:
            raise RuntimeError("resource hash reader is closed")
        if self._direct and self._read_direct(path, consume):
            return
        buffer = self._read_buffer()
        with path.open("rb", buffering=0) as handle:
            size = os.fstat(handle.fileno()).st_size
            total = 0
            while True:
                length = handle.readinto(buffer)
                if length is None:
                    raise OSError(
                        errno.EIO, "resource read made no progress", str(path)
                    )
                if not length:
                    break
                self._consume(buffer, length, consume)
                total += length
            self._require_eof(path, total, size, os.fstat(handle.fileno()).st_size)

    def _read_direct(self, path: Path, consume: Callable[[memoryview], None]) -> bool:
        try:
            descriptor = os.open(path, os.O_RDONLY | self._direct)
        except OSError as error:
            if error.errno in _UNSUPPORTED_DIRECT:
                return False
            raise
        try:
            buffer = self._read_buffer()
            size = os.fstat(descriptor).st_size
            try:
                length = os.readv(descriptor, [buffer])
            except OSError as error:
                if error.errno in _UNSUPPORTED_DIRECT:
                    return False
                raise
            total = 0
            while length:
                self._consume(buffer, length, consume)
                total += length
                if length < len(buffer):
                    break
                # No fallback is allowed after the first consumed byte.
                length = os.readv(descriptor, [buffer])
            self._require_eof(path, total, size, os.fstat(descriptor).st_size)
            return True
        finally:
            os.close(descriptor)

    @staticmethod
    def _consume(
        buffer: mmap.mmap, length: int, consume: Callable[[memoryview], None]
    ) -> None:
        view = memoryview(buffer)[:length]
        try:
            consume(view)
        finally:
            view.release()

    @staticmethod
    def _require_eof(
        path: Path, total: int, initial_size: int, final_size: int
    ) -> None:
        if total != initial_size or final_size != initial_size:
            raise OSError(
                errno.EIO, "resource changed or read ended before EOF", str(path)
            )
