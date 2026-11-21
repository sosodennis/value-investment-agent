"""Independent consumers reuse pure image data while re-proving their boundary."""

import multiprocessing
import os
from asyncio import CancelledError
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import pytest

import fundamental_service.parser_action_identity as identity


@pytest.fixture
def runtime(monkeypatch):
    configuration = ["immutable image"]
    scans = []
    checks = []

    def boundary():
        checks.append(configuration[0])
        return configuration[0], ()

    def scan(**kwargs):
        scans.append(configuration[0])
        return identity.sha256_digest(configuration[0])

    monkeypatch.setattr(identity, "_immutable_build_configuration", boundary)
    monkeypatch.setattr(identity, "_files", lambda path: (("code.py", "1" * 64),))
    monkeypatch.setattr(identity, "_runtime_identity", scan)
    return SimpleNamespace(configuration=configuration, scans=scans, checks=checks)


def observe_waiters(monkeypatch, expected):
    lock = identity._BUILD_LOCK
    counter_lock = Lock()
    attempted = Event()
    count = 0

    class ObservedLock:
        def __enter__(self):
            nonlocal count
            with counter_lock:
                count += 1
                if count == expected:
                    attempted.set()
            lock.acquire()

        def __exit__(self, *args):
            lock.release()

    monkeypatch.setattr(identity, "_BUILD_LOCK", ObservedLock())
    return attempted


def test_independent_consumers_match_full_build_and_reprove_every_use(runtime):
    full = identity.ParserBuildChecks(share_image=False).current()
    consumers = [identity.ParserBuildChecks() for _ in range(7)]
    assert all(consumer.current() == full for consumer in consumers)
    assert len(runtime.scans) == 2
    before = len(runtime.checks)
    for consumer in consumers:
        consumer.verify()
    assert len(runtime.checks) == before + len(consumers)
    runtime.configuration[0] = "different image"
    for consumer in consumers:
        with pytest.raises(identity.IncompleteParserClosure):
            consumer.verify()
    changed = identity.ParserBuildChecks().current()
    assert changed != full
    assert identity.ParserBuildChecks(share_image=False).current() == changed


def test_configuration_churn_keeps_one_value_and_never_rebinds_consumers(runtime):
    old = identity.ParserBuildChecks()
    first = old.current()
    for number in range(5):
        runtime.configuration[0] = f"image {number}"
        assert identity.ParserBuildChecks().current() != first
        with pytest.raises(identity.IncompleteParserClosure):
            old.current()
    runtime.configuration[0] = "immutable image"
    assert old.current() == first
    before = len(runtime.scans)
    assert identity.ParserBuildChecks().current() == first
    assert len(runtime.scans) == before + 1


@pytest.mark.parametrize(
    "failure",
    [OSError("read failed"), MemoryError(), KeyboardInterrupt(), CancelledError()],
)
def test_failed_or_cancelled_initialization_publishes_no_build_and_can_retry(
    runtime, monkeypatch, failure
):
    scan = identity._runtime_identity

    def fail(**kwargs):
        raise failure

    monkeypatch.setattr(identity, "_runtime_identity", fail)
    consumer = identity.ParserBuildChecks()
    with pytest.raises(type(failure)):
        consumer.current()
    assert identity._SHARED_BUILD is None
    assert consumer._build is None and consumer._configuration is None
    monkeypatch.setattr(identity, "_runtime_identity", scan)
    assert consumer.current() == identity.ParserBuildChecks(share_image=False).current()


def test_boundary_change_during_scan_cannot_publish_partial_binding(
    runtime, monkeypatch
):
    scan = identity._runtime_identity

    def change(**kwargs):
        result = scan(**kwargs)
        runtime.configuration[0] = "changed during scan"
        return result

    monkeypatch.setattr(identity, "_runtime_identity", change)
    with pytest.raises(identity.IncompleteParserClosure):
        identity.ParserBuildChecks().current()
    assert identity._SHARED_BUILD is None
    monkeypatch.setattr(identity, "_runtime_identity", scan)
    assert (
        identity.ParserBuildChecks().current().runtime_digest
        == identity.sha256_digest("changed during scan")
    )


@pytest.mark.parametrize(
    "failure", [OSError("replacement unreadable"), MemoryError(), CancelledError()]
)
def test_failed_replacement_preserves_old_value_without_binding_new_consumer(
    runtime, monkeypatch, failure
):
    old = identity.ParserBuildChecks()
    first = old.current()
    scan = identity._runtime_identity
    runtime.configuration[0] = "replacement image"

    def fail(**kwargs):
        raise failure

    monkeypatch.setattr(identity, "_runtime_identity", fail)
    new = identity.ParserBuildChecks()
    with pytest.raises(type(failure)):
        new.current()
    assert new._build is None and new._configuration is None
    runtime.configuration[0] = "immutable image"
    assert old.current() == identity.ParserBuildChecks().current() == first
    monkeypatch.setattr(identity, "_runtime_identity", scan)


def test_cached_build_does_not_authorize_unsupported_boundary(runtime, monkeypatch):
    consumer = identity.ParserBuildChecks()
    consumer.current()

    def unsupported():
        raise identity.IncompleteParserClosure("writable mount")

    monkeypatch.setattr(identity, "_immutable_build_configuration", unsupported)
    for scope in (consumer, identity.ParserBuildChecks()):
        with pytest.raises(identity.IncompleteParserClosure):
            scope.current()
    with pytest.raises(identity.IncompleteParserClosure):
        consumer.verify()


def test_concurrent_first_consumers_share_only_one_completed_scan(runtime, monkeypatch):
    started, release = Event(), Event()
    attempted = observe_waiters(monkeypatch, 4)
    scan = identity._runtime_identity

    def blocked(**kwargs):
        started.set()
        assert release.wait(5)
        return scan(**kwargs)

    monkeypatch.setattr(identity, "_runtime_identity", blocked)
    with ThreadPoolExecutor(max_workers=4) as executor:
        first = executor.submit(identity.ParserBuildChecks().current)
        assert started.wait(5)
        others = [
            executor.submit(identity.ParserBuildChecks().current) for _ in range(3)
        ]
        assert attempted.wait(5)
        release.set()
        expected = first.result(timeout=5)
        assert all(result.result(timeout=5) == expected for result in others)
    assert len(runtime.scans) == 1


def test_waiting_consumer_proves_boundary_after_lock_wait(runtime, monkeypatch):
    started, release = Event(), Event()
    attempted = observe_waiters(monkeypatch, 2)
    scan = identity._runtime_identity

    def blocked(**kwargs):
        if not started.is_set():
            started.set()
            assert release.wait(5)
        return scan(**kwargs)

    monkeypatch.setattr(identity, "_runtime_identity", blocked)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(identity.ParserBuildChecks().current)
        assert started.wait(5)
        waiting = executor.submit(identity.ParserBuildChecks().current)
        assert attempted.wait(5)
        runtime.configuration[0] = "changed while waiting"
        release.set()
        with pytest.raises(identity.IncompleteParserClosure):
            first.result(timeout=5)
        assert waiting.result(timeout=5).runtime_digest == identity.sha256_digest(
            "changed while waiting"
        )


@pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods(), reason="requires fork"
)
def test_fork_discards_inherited_lock_shared_value_and_consumer_memo(
    runtime, monkeypatch
):
    def process_digest(**kwargs):
        return identity.sha256_digest(os.getpid())

    monkeypatch.setattr(identity, "_runtime_identity", process_digest)
    inherited = identity.ParserBuildChecks()
    parent = inherited.current()
    context = multiprocessing.get_context("fork")
    receiver, sender = context.Pipe(duplex=False)

    def child():
        inherited.verify()
        sender.send((os.getpid(), inherited.current().runtime_digest))
        sender.close()

    process = context.Process(target=child)
    held, release = Event(), Event()

    def hold_lock():
        with identity._BUILD_LOCK:
            held.set()
            assert release.wait(10)

    with ThreadPoolExecutor(max_workers=1) as executor:
        holding = executor.submit(hold_lock)
        assert held.wait(5)
        process.start()
        sender.close()
        try:
            assert receiver.poll(5), "child inherited a locked image initializer"
            pid, digest = receiver.recv()
        finally:
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join()
            receiver.close()
            release.set()
        holding.result(timeout=5)
    assert process.exitcode == 0
    assert digest == identity.sha256_digest(pid) != parent.runtime_digest
    assert inherited.current() == parent


@pytest.fixture
def immutable_kernel(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("LD_") or name in {
            "XML_CATALOG_FILES",
            "SGML_CATALOG_FILES",
            "GCONV_PATH",
            "LOCPATH",
            "TZDIR",
            "GLIBC_TUNABLES",
        }:
            monkeypatch.delenv(name)
    original = Path.read_text
    mount = ["1 0 0:1 / / ro - overlay overlay ro\n"]

    def read(path, *args, **kwargs):
        if str(path) == "/proc/self/status":
            return "CapEff: 0\nCapPrm: 0\nCapAmb: 0\nNoNewPrivs: 1\n"
        if str(path) == "/proc/self/mountinfo":
            return mount[0]
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(Path, "exists", lambda path: False)
    monkeypatch.setattr(identity.sys, "platform", "linux")
    monkeypatch.setattr(identity.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(
        identity.os, "statvfs", lambda path: SimpleNamespace(f_flag=os.ST_RDONLY)
    )
    monkeypatch.setattr(identity.sys, "path", ["", *identity.sys.path])
    return mount


@pytest.mark.parametrize(
    "name",
    [
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "XML_CATALOG_FILES",
        "SGML_CATALOG_FILES",
        "GCONV_PATH",
        "LOCPATH",
        "TZDIR",
        "GLIBC_TUNABLES",
    ],
)
def test_kernel_configuration_refuses_external_configuration(
    monkeypatch, immutable_kernel, name
):
    monkeypatch.setenv(name, "/outside-image")
    with pytest.raises(identity.IncompleteParserClosure, match="external"):
        identity._immutable_build_configuration()


@pytest.mark.parametrize(
    "change",
    [
        "environment",
        "imports",
        "executable",
        "version",
        "flags",
        "options",
        "mounts",
        "groups",
        "cwd",
    ],
)
def test_kernel_configuration_key_covers_execution_dependencies(
    tmp_path, monkeypatch, immutable_kernel, change
):
    first = identity._immutable_build_configuration()[0]
    if change == "environment":
        monkeypatch.setenv("FUNDAMENTAL_TEST_IMAGE_SETTING", "changed")
    elif change == "imports":
        monkeypatch.setattr(
            identity.sys, "path", [*identity.sys.path, "/app/different"]
        )
    elif change == "executable":
        monkeypatch.setattr(identity.sys, "executable", "/usr/bin/different-python")
    elif change == "version":
        monkeypatch.setattr(identity.sys, "version", "different Python")
    elif change == "flags":
        monkeypatch.setattr(identity.sys, "flags", "different flags")
    elif change == "options":
        monkeypatch.setattr(
            identity.sys, "_xoptions", {**identity.sys._xoptions, "utf8": "1"}
        )
    elif change == "mounts":
        immutable_kernel[0] += "2 1 0:2 / /run/resources ro - ext4 /dev/resource ro\n"
    elif change == "cwd":
        monkeypatch.chdir(tmp_path)
    else:
        monkeypatch.setattr(identity.os, "getgroups", lambda: [87654])
    assert identity._immutable_build_configuration()[0] != first


def test_relative_import_change_rechecks_shared_and_full_admission(
    tmp_path, monkeypatch, immutable_kernel
):
    allowed = tmp_path / "image"
    outside = tmp_path / "mutable"
    allowed.mkdir()
    outside.mkdir()
    monkeypatch.chdir(allowed)
    monkeypatch.setattr(identity, "_files", lambda path: (("code.py", "1" * 64),))

    def admitted(**kwargs):
        if Path.cwd() != allowed:
            raise identity.IncompleteParserClosure(
                "Python import path escapes the image closure"
            )
        return "2" * 64

    monkeypatch.setattr(identity, "_runtime_identity", admitted)
    consumer = identity.ParserBuildChecks()
    consumer.current()
    monkeypatch.chdir(outside)
    with pytest.raises(identity.IncompleteParserClosure):
        consumer.verify()
    for shared in (True, False):
        with pytest.raises(
            identity.IncompleteParserClosure, match="import path escapes"
        ):
            identity.ParserBuildChecks(share_image=shared).current()
