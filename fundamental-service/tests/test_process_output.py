"""Subprocess protocols retain complete bytes despite short unbuffered writes."""

import importlib
import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from fundamental_service import automatic_caller_http
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


def test_http_main_emits_complete_body_without_newline(monkeypatch):
    writer = ShortWriter()
    raw = canonical_bytes({"body": "數值" * 2000})
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=writer))
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr(automatic_caller_http, "read_response", lambda wire: raw)
    assert automatic_caller_http.main() == 0
    assert bytes(writer.raw) == raw
    assert writer.flushed


@pytest.mark.parametrize("failure", ["zero", "none", "write", "flush"])
def test_http_main_sanitizes_output_failures(monkeypatch, failure):
    stop = {
        "zero": lambda: 0,
        "none": lambda: None,
        "write": OSError("private credential"),
        "flush": None,
    }[failure]
    writer = ShortWriter(stop=stop, fail_flush=failure == "flush")
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=writer))
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr(automatic_caller_http, "read_response", lambda wire: b"x" * 100)
    assert automatic_caller_http.main() == 3
    assert json.loads(stderr.getvalue()) == {"transport_failed": True}


@pytest.mark.parametrize("as_module", [False, True])
def test_http_worker_imports_standalone_and_as_package(tmp_path, as_module):
    source = Path(automatic_caller_http.__file__).resolve()
    command = (
        ["-m", "fundamental_service.automatic_caller_http"]
        if as_module
        else [str(source)]
    )
    result = subprocess.run(
        [sys.executable, "-u", *command],
        input=b"{}",
        capture_output=True,
        cwd=tmp_path,
        timeout=15,
    )
    assert result.returncode == 3
    assert result.stdout == b""
    assert json.loads(result.stderr) == {"transport_failed": True}


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
