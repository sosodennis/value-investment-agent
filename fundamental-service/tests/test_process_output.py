"""Subprocess protocols retain complete bytes despite short unbuffered writes."""

import importlib
import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from fundamental_service.process_output import write_stdout
from fundamental_service.serialization import canonical_bytes


class ShortWriter:
    def __init__(self, *, stop=None, fail_flush=False):
        self.raw = bytearray()
        self.stop = stop
        self.fail_flush = fail_flush
        self.flushed = False

    def write(self, raw):
        if self.raw and self.stop is not None:
            if isinstance(self.stop, Exception):
                raise self.stop
            return self.stop()
        count = min(17, len(raw))
        self.raw.extend(raw[:count])
        return count

    def flush(self):
        if self.fail_flush:
            raise OSError("private output failure")
        self.flushed = True


def test_stdout_completes_short_writes_and_flushes(monkeypatch):
    writer = ShortWriter()
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=writer))
    raw = ("數值\n".encode() + bytes(range(256))) * 3000
    write_stdout(raw)
    assert bytes(writer.raw) == raw
    assert writer.flushed


@pytest.mark.parametrize("stop", [lambda: 0, lambda: None, OSError("private failure")])
def test_stdout_partial_failure_does_not_report_success(monkeypatch, stop):
    writer = ShortWriter(stop=stop)
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=writer))
    with pytest.raises(OSError):
        write_stdout(b"x" * 100)
    assert bytes(writer.raw) == b"x" * 17
    assert not writer.flushed


def test_stdout_flush_failure_propagates(monkeypatch):
    writer = ShortWriter(fail_flush=True)
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=writer))
    with pytest.raises(OSError, match="private output failure"):
        write_stdout(b"complete")


@pytest.mark.parametrize(
    ("module_name", "arguments"),
    [
        ("annual_discovery_runner", ["--artifact-id", "annual:test"]),
        (
            "preparation_runner",
            [
                "--plan",
                "unused",
                "--plan-digest",
                "a" * 64,
                "--actor",
                "a",
                "--organization",
                "o",
            ],
        ),
        (
            "issuer_preparation_runner",
            [
                "--cik",
                "789019",
                "--valuation-timestamp",
                "2025-01-01T00:00:00Z",
                "--source-revision",
                "a" * 40,
                "--source-plan-configuration",
                "unused",
                "--configuration-digest",
                "b" * 64,
            ],
        ),
    ],
)
@pytest.mark.parametrize("fails", [False, True])
def test_cli_output_completes_or_returns_failure(
    monkeypatch, module_name, arguments, fails
):
    module = importlib.import_module("fundamental_service." + module_name)
    result = {"receipt": "數值" * 2000}

    async def run_command(args):
        return result

    if module_name == "issuer_preparation_runner":
        monkeypatch.setattr(module, "_execute", lambda args: result)
    else:
        monkeypatch.setattr(module, "_run_command", run_command)
    writer = ShortWriter(stop=(lambda: 0) if fails else None)
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=writer))
    assert module.main(arguments) == (2 if fails else 0)
    if not fails:
        assert bytes(writer.raw) == canonical_bytes(result) + b"\n"
        assert writer.flushed


DESCRIPTOR_CHILD = r"""
import json,os,sys,time
from fundamental_service.process_output import write_stdout
os.set_inheritable(sys.stdout.fileno(),False)
original_blocking=os.get_blocking(sys.stdout.fileno())
original_inheritable=os.get_inheritable(sys.stdout.fileno())
sys.stdout.write('pending text')
sys.stdout.buffer.write(b'pending bytes')
deadline=time.monotonic()+float(os.environ.get('OUTPUT_BUDGET_SECONDS','10'))
def budget():
    remaining=deadline-time.monotonic()
    if remaining<=0:
        raise KeyboardInterrupt
    return remaining
try:
    write_stdout(bytes(range(256))*8192,remaining_budget=budget)
except KeyboardInterrupt:
    sys.stderr.write(json.dumps({'cancelled':True,'flags_restored':os.get_blocking(sys.stdout.fileno())==original_blocking and os.get_inheritable(sys.stdout.fileno())==original_inheritable})+'\n')
    raise SystemExit(3)
sys.stderr.write(json.dumps({'cancelled':False,'flags_restored':os.get_blocking(sys.stdout.fileno())==original_blocking and os.get_inheritable(sys.stdout.fileno())==original_inheritable})+'\n')
"""


def test_budgeted_stdout_drains_pending_bytes_and_large_output_with_slow_reader():
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", DESCRIPTOR_CHILD],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert process.stdout is not None
        observed = bytearray()
        while block := process.stdout.read(4096):
            observed.extend(block)
            time.sleep(0.001)
        assert process.wait(timeout=10) == 0
        assert process.stderr is not None
        assert json.loads(process.stderr.read()) == {
            "cancelled": False,
            "flags_restored": True,
        }
        assert bytes(observed) == (
            b"pending bytespending text" + bytes(range(256)) * 8192
        )
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def test_budgeted_stdout_cancellation_restores_flags_and_discards_pending_buffer():
    read_fd, write_fd = os.pipe()
    process = None
    try:
        os.set_blocking(write_fd, False)
        while True:
            try:
                os.write(write_fd, b"x" * 4096)
            except BlockingIOError:
                break
        os.set_blocking(write_fd, True)
        environment = os.environ.copy()
        environment["OUTPUT_BUDGET_SECONDS"] = "0.1"
        process = subprocess.Popen(
            [sys.executable, "-B", "-c", DESCRIPTOR_CHILD],
            stdout=write_fd,
            stderr=subprocess.PIPE,
            env=environment,
        )
        os.close(write_fd)
        write_fd = -1
        assert process.wait(timeout=5) == 3
        assert process.stderr is not None
        assert json.loads(process.stderr.read()) == {
            "cancelled": True,
            "flags_restored": True,
        }
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            if process.stderr is not None:
                process.stderr.close()
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)
