"""Complete byte output for subprocess protocols, including unbuffered pipes."""

import sys


def write_stdout(raw: bytes) -> None:
    remaining = memoryview(raw)
    while remaining:
        written = sys.stdout.buffer.write(remaining)
        if written is None or written <= 0:
            raise OSError("stdout write made no progress")
        remaining = remaining[written:]
    sys.stdout.buffer.flush()
