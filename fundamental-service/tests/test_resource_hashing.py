"""Resource scans preserve complete bytes, bounded reads and explicit failures."""

import errno
import hashlib
import mmap
import os
from asyncio import CancelledError

import pytest

import fundamental_service.resource_hashing as resources


@pytest.fixture
def direct_calls(monkeypatch):
    """Exercise direct control flow portably, with real regular-file reads."""
    original_open = os.open
    original_readv = getattr(os, "readv", None)
    opened = []
    closed = []
    original_close = os.close
    flag = getattr(os, "O_DIRECT", 0x40000000)

    def open_file(path, flags, *args, **kwargs):
        descriptor = original_open(path, flags & ~flag, *args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def close(descriptor):
        closed.append(descriptor)
        return original_close(descriptor)

    monkeypatch.setattr(resources.sys, "platform", "linux")
    monkeypatch.setattr(os, "O_DIRECT", flag, raising=False)
    monkeypatch.setattr(os, "open", open_file)
    monkeypatch.setattr(os, "close", close)
    if original_readv is None:
        pytest.skip("readv is required for direct-path control tests")
    return opened, closed, original_readv


@pytest.mark.parametrize("size", [0, 1, 511, 4097, 1024 * 1024, 2 * 1024 * 1024 + 13])
@pytest.mark.parametrize("direct", [False, True])
def test_exact_bytes_across_empty_unaligned_and_multiple_buffers(
    tmp_path, monkeypatch, direct_calls, size, direct
):
    raw = (bytes(range(256)) * (size // 256 + 1))[:size]
    path = tmp_path / "resource"
    path.write_bytes(raw)
    digest = hashlib.sha256()
    buffers = []
    views = []

    def consume(view):
        assert 0 < len(view) <= 1024 * 1024
        buffers.append(view.obj)
        views.append(view)
        digest.update(view)

    with resources.ResourceHashReader(direct=direct) as reader:
        reader.update(path, consume)
    assert digest.hexdigest() == hashlib.sha256(raw).hexdigest()
    assert not buffers or all(buffer is buffers[0] for buffer in buffers)
    assert all(buffer.closed for buffer in buffers)
    for view in views:
        with pytest.raises(ValueError):
            len(view)
    with pytest.raises(RuntimeError):
        reader.update(path, consume)
    if direct:
        assert direct_calls[0] == direct_calls[1]


def test_directory_scan_reuses_and_closes_one_buffer(tmp_path, direct_calls):
    buffers = []
    with resources.ResourceHashReader() as reader:
        for number in range(3):
            path = tmp_path / str(number)
            path.write_bytes(b"complete content")
            reader.update(path, lambda view: buffers.append(view.obj))
    assert len(buffers) == 3 and all(buffer is buffers[0] for buffer in buffers)
    assert buffers[0].closed


@pytest.mark.parametrize("stage", ["open", "first-read"])
@pytest.mark.parametrize("error_number", [errno.EINVAL, errno.EOPNOTSUPP, errno.ENOSYS])
def test_unsupported_direct_io_falls_back_before_any_content_is_consumed(
    tmp_path, monkeypatch, direct_calls, stage, error_number
):
    path = tmp_path / "resource"
    raw = b"same bytes exactly once" * 100
    path.write_bytes(raw)
    direct_open = os.open

    def unsupported(*args, **kwargs):
        raise OSError(error_number, "direct IO unsupported")

    if stage == "open":
        monkeypatch.setattr(os, "open", unsupported)
    else:
        monkeypatch.setattr(os, "readv", unsupported)
    digest = hashlib.sha256()
    count = []

    def consume(view):
        count.append(len(view))
        digest.update(view)

    with resources.ResourceHashReader() as reader:
        reader.update(path, consume)
    assert sum(count) == len(raw)
    assert digest.hexdigest() == hashlib.sha256(raw).hexdigest()
    assert direct_calls[0] == direct_calls[1]
    monkeypatch.setattr(os, "open", direct_open)


@pytest.mark.parametrize(
    "failure",
    [OSError(errno.EINVAL, "hash callback failed"), MemoryError(), CancelledError()],
)
@pytest.mark.parametrize("direct", [False, True])
def test_callback_failure_never_restarts_or_falls_back_and_releases_memory(
    tmp_path, direct_calls, failure, direct
):
    path = tmp_path / "resource"
    path.write_bytes(b"resource")
    seen = []

    def fail(view):
        seen.append(view.obj)
        raise failure

    with pytest.raises(type(failure)):
        with resources.ResourceHashReader(direct=direct) as reader:
            reader.update(path, fail)
    assert len(seen) == 1 and seen[0].closed
    assert direct_calls[0] == direct_calls[1]


@pytest.mark.parametrize("error_number", [errno.EINVAL, errno.EIO])
def test_midstream_failure_cannot_restart_partially_consumed_hash(
    tmp_path, monkeypatch, direct_calls, error_number
):
    path = tmp_path / "resource"
    path.write_bytes(b"x" * (1024 * 1024 + 1))
    read = direct_calls[2]
    calls = []

    def interrupted(descriptor, buffers):
        if calls:
            raise OSError(error_number, "second read failed")
        calls.append(True)
        return read(descriptor, buffers)

    monkeypatch.setattr(os, "readv", interrupted)
    consumed = []
    with pytest.raises(OSError):
        with resources.ResourceHashReader() as reader:
            reader.update(path, lambda view: consumed.append(len(view)))
    assert consumed == [1024 * 1024]
    assert direct_calls[0] == direct_calls[1]


@pytest.mark.parametrize("length", [0, 1])
def test_non_eof_short_or_zero_direct_read_refuses_incomplete_content(
    tmp_path, monkeypatch, direct_calls, length
):
    path = tmp_path / "resource"
    path.write_bytes(b"longer than the incomplete read")
    monkeypatch.setattr(os, "readv", lambda *args: length)
    with pytest.raises(OSError, match="before EOF"):
        with resources.ResourceHashReader() as reader:
            reader.update(path, lambda view: None)
    assert direct_calls[0] == direct_calls[1]


@pytest.mark.parametrize("initial", [b"", b"short", b"x" * (1024 * 1024)])
@pytest.mark.parametrize("direct", [False, True])
def test_changed_file_size_at_final_boundary_is_refused(
    tmp_path, monkeypatch, direct_calls, initial, direct
):
    path = tmp_path / "resource"
    path.write_bytes(initial)
    fstat = os.fstat
    calls = []

    def changed(descriptor):
        if calls:
            with path.open("ab") as handle:
                handle.write(b"changed")
        calls.append(True)
        return fstat(descriptor)

    monkeypatch.setattr(os, "fstat", changed)
    with pytest.raises(OSError, match="resource changed"):
        with resources.ResourceHashReader(direct=direct) as reader:
            reader.update(path, lambda view: None)


def test_buffer_allocation_failure_closes_open_descriptor(
    tmp_path, monkeypatch, direct_calls
):
    path = tmp_path / "resource"
    path.write_bytes(b"content")

    def fail(*args, **kwargs):
        raise MemoryError()

    monkeypatch.setattr(mmap, "mmap", fail)
    with pytest.raises(MemoryError):
        with resources.ResourceHashReader() as reader:
            reader.update(path, lambda view: None)
    assert direct_calls[0] == direct_calls[1]


def test_missing_and_permission_errors_never_become_supported_fallback(
    tmp_path, monkeypatch, direct_calls
):
    with pytest.raises(FileNotFoundError):
        with resources.ResourceHashReader() as reader:
            reader.update(tmp_path / "missing", lambda view: None)

    def denied(*args, **kwargs):
        raise PermissionError(errno.EACCES, "denied resource")

    monkeypatch.setattr(os, "open", denied)
    with pytest.raises(PermissionError):
        with resources.ResourceHashReader() as reader:
            reader.update(tmp_path / "denied", lambda view: None)


@pytest.mark.parametrize("unsupported", ["platform", "readv", "flag"])
def test_platform_without_direct_support_uses_complete_buffered_bytes(
    tmp_path, monkeypatch, direct_calls, unsupported
):
    path = tmp_path / "resource"
    raw = b"portable full content"
    path.write_bytes(raw)
    if unsupported == "platform":
        monkeypatch.setattr(resources.sys, "platform", "darwin")
    else:
        monkeypatch.delattr(os, "readv" if unsupported == "readv" else "O_DIRECT")

    def unexpected(*args, **kwargs):
        raise AssertionError("unsupported platform attempted direct open")

    monkeypatch.setattr(os, "open", unexpected)
    digest = hashlib.sha256()
    with resources.ResourceHashReader() as reader:
        reader.update(path, digest.update)
    assert digest.hexdigest() == hashlib.sha256(raw).hexdigest()
