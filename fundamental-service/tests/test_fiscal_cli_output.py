from __future__ import annotations

import json
import os
from pathlib import Path
import select
import subprocess
import sys

import pytest


CLI_CHILD = r"""
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import fundamental_service.fiscal_source_runner as runner
from test_fiscal_discovery import DiscoveryHarness

with TemporaryDirectory() as root:
    harness = DiscoveryHarness(Path(root))
    evidence, publication = harness.publish()
    result = runner._FiscalCommandOutput(evidence=evidence, publication=publication)
    async def ready_result(args, *, deadline_at):
        if os.getenv('SYNTHETIC_PENDING_STDOUT'):
            sys.stdout.write('pending text')
            sys.stdout.buffer.write(b'pending bytes')
        sys.stderr.write('SYNTHETIC_RESULT_READY\n')
        sys.stderr.flush()
        return result
    runner._run = ready_result
    raise SystemExit(runner.main([
        '--source-revision', 'a'*40, '--timeout-seconds', '1',
        'read', '--artifact-id', 'synthetic-retained-discovery'
    ]))
"""


def _child_environment(*, pending: bool = False) -> dict[str, str]:
    environment = os.environ.copy()
    tests = str(Path(__file__).resolve().parent)
    environment["PYTHONPATH"] = os.pathsep.join(
        (tests, environment.get("PYTHONPATH", ""))
    )
    if pending:
        environment["SYNTHETIC_PENDING_STDOUT"] = "1"
    return environment


@pytest.mark.parametrize("pending", [False, True])
def test_cli_exits_on_stdout_deadline_without_a_reader(pending: bool) -> None:
    read_fd, write_fd = os.pipe()
    process: subprocess.Popen[bytes] | None = None
    try:
        os.set_blocking(write_fd, False)
        while True:
            try:
                os.write(write_fd, b"x" * 4096)
            except BlockingIOError:
                break
        os.set_blocking(write_fd, True)
        process = subprocess.Popen(
            [sys.executable, "-B", "-c", CLI_CHILD],
            stdout=write_fd,
            stderr=subprocess.PIPE,
            env=_child_environment(pending=pending),
        )
        os.close(write_fd)
        write_fd = -1
        assert process.stderr is not None
        assert select.select([process.stderr], [], [], 10)[0]
        assert process.stderr.readline() == b"SYNTHETIC_RESULT_READY\n"
        try:
            code = process.wait(timeout=2.5)
        except subprocess.TimeoutExpired:
            pytest.fail("CLI remained blocked beyond its one-second deadline")
        assert code == 2
        assert json.loads(process.stderr.read()) == {
            "error_code": "REQUEST_DEADLINE_EXCEEDED",
            "retryable": True,
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


def test_cli_reports_closed_stdout_without_shutdown_flush_hanging() -> None:
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", CLI_CHILD],
        stdout=write_fd,
        stderr=subprocess.PIPE,
        env=_child_environment(pending=True),
    )
    os.close(write_fd)
    try:
        _, error = process.communicate(timeout=10)
        assert process.returncode == 2
        marker, message = error.split(b"\n", maxsplit=1)
        assert marker == b"SYNTHETIC_RESULT_READY"
        assert json.loads(message) == {"error_code": "FISCAL_VALIDATION_IO_FAILED"}
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_cli_drains_complete_typed_json() -> None:
    result = subprocess.run(
        [sys.executable, "-B", "-c", CLI_CHILD],
        capture_output=True,
        env=_child_environment(),
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stderr == b"SYNTHETIC_RESULT_READY\n"
    assert result.stdout.endswith(b"\n")
    value = json.loads(result.stdout)
    assert value["evidence"]["protocol"] == "fundamental.fiscal-discovery-evidence.v1"
    assert value["publication"]["wrote"] is True
