"""The deployed budget must apply to independent installed CLI processes."""

import os
import json
import select
import subprocess
import sys
from pathlib import Path

import pytest

from fundamental_service.arelle_parser import (
    ArelleParserError,
    ArelleValidationProfileV1,
    ParserResourcePolicy,
    _claim_parser_process_slot,
    parse_filing_offline,
)


def _parse(directory: Path, capacity: int = 1):
    return parse_filing_offline(
        Path(__file__).parent / "fixtures" / "simple.xbrl",
        profile=ArelleValidationProfileV1(profile_id="sec-efm-us-gaap-v1"),
        taxonomy_version="fixture-taxonomy-v1",
        resource_policy=ParserResourcePolicy(
            slot_directory=directory, max_concurrency=capacity
        ),
    )


@pytest.mark.parametrize("capacity", [1, 2])
def test_independent_parser_workers_share_capacity_and_release_after_exit(
    tmp_path: Path, capacity: int
):
    directory = tmp_path / "slots"
    held = []
    try:
        for _ in range(capacity):
            descriptor = _claim_parser_process_slot(directory, capacity)
            assert descriptor is not None
            held.append(descriptor)
        with pytest.raises(ArelleParserError) as failure:
            _parse(directory, capacity)
        assert failure.value.code == "PARSER_CONCURRENCY_EXHAUSTED"
        os.close(held.pop())
        assert _parse(directory, capacity).facts
        assert _parse(directory, capacity).facts
    finally:
        for descriptor in held:
            os.close(descriptor)


def test_process_death_releases_budget_without_deleting_slot_files(tmp_path: Path):
    script = """
import sys
from pathlib import Path
from fundamental_service.arelle_parser import _claim_parser_process_slot
descriptor = _claim_parser_process_slot(Path(sys.argv[1]), 1)
print('claimed', flush=True)
sys.stdin.readline()
"""
    directory = tmp_path / "slots"
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(directory)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
    )
    try:
        assert process.stdout is not None
        assert select.select([process.stdout], [], [], 15)[0]
        assert process.stdout.readline().strip() == "claimed"
        with pytest.raises(ArelleParserError) as failure:
            _parse(directory)
        assert failure.value.code == "PARSER_CONCURRENCY_EXHAUSTED"
        inode = (directory / "slot-0.lock").stat().st_ino
        process.kill()
        process.wait(timeout=5)
        assert _parse(directory).facts
        assert (directory / "slot-0.lock").stat().st_ino == inode
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_worker_exception_releases_budget(tmp_path: Path):
    directory = tmp_path / "slots"
    inline_path = tmp_path / "missing-cache.htm"
    inline_path.write_text("<html></html>")
    with pytest.raises(ArelleParserError) as failure:
        parse_filing_offline(
            inline_path,
            profile=ArelleValidationProfileV1(profile_id="sec-efm-us-gaap-v1"),
            taxonomy_version="fixture-taxonomy-v1",
            resource_policy=ParserResourcePolicy(slot_directory=directory),
        )
    assert failure.value.code == "TAXONOMY_CACHE_REQUIRED"
    assert _parse(directory).facts


@pytest.mark.parametrize("kind", ["file", "public", "symlink"])
def test_unusable_budget_directory_refuses_without_fallback(tmp_path: Path, kind: str):
    directory = tmp_path / "slots"
    if kind == "file":
        directory.write_text("not a directory")
    elif kind == "public":
        directory.mkdir(mode=0o755)
    else:
        target = tmp_path / "target"
        target.mkdir(mode=0o700)
        directory.symlink_to(target, target_is_directory=True)
    with pytest.raises(ArelleParserError) as failure:
        _parse(directory)
    assert failure.value.code == "PARSER_RESOURCE_POLICY_UNAVAILABLE"


def test_deployment_slot_policy_is_explicit_and_absolute(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FUNDAMENTAL_SEC_PARSER_SLOT_DIRECTORY", str(tmp_path))
    assert ParserResourcePolicy.from_env().validate().slot_directory == tmp_path
    monkeypatch.setenv("FUNDAMENTAL_SEC_PARSER_SLOT_DIRECTORY", "relative-path")
    with pytest.raises(ArelleParserError) as failure:
        ParserResourcePolicy.from_env().validate()
    assert failure.value.code == "PARSER_RESOURCE_POLICY_INVALID"
    monkeypatch.delenv("FUNDAMENTAL_SEC_PARSER_SLOT_DIRECTORY")
    assert ParserResourcePolicy.from_env().slot_directory is None


def test_separate_containers_do_not_share_slots(tmp_path: Path):
    descriptor = _claim_parser_process_slot(tmp_path / "container-a", 1)
    assert descriptor is not None
    try:
        assert _parse(tmp_path / "container-b").facts
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("end_reason", ["parent_exit", "deadline"])
def test_orphan_or_timed_out_worker_releases_slot_during_result_serialization(
    tmp_path: Path, end_reason: str
):
    script = tmp_path / "blocked_result.py"
    script.write_text("""
import json, multiprocessing, os, sys, tempfile, time
from datetime import datetime, timedelta, timezone
from multiprocessing.connection import Connection
from pathlib import Path
from fundamental_service import arelle_parser as parser

class LargeReport:
    def model_copy(self, **kwargs): return self
    def model_dump(self, **kwargs): return {"payload": "x" * (8 * 1024 * 1024)}

def run_worker(output, directory, deadline, scratch):
    def fake_parse(path, profile, *args):
        parser._validation_plugin_root(profile)
        return LargeReport()
    parser._parse_in_process = fake_parse
    store_result = parser._store_worker_result
    def blocked_writer(result_file, payload):
        store_result(result_file, payload)
        Path(directory, "serializing").write_text("large output retained before worker exit")
        while True: time.sleep(0.01)
    parser._store_worker_result = blocked_writer
    profile = {"profile_id": "fixture", "edgar_plugin_dir": str(Path(directory, "edgar")),
               "xule_plugin_dir": str(Path(directory, "xule"))}
    parser._parse_worker(output, "unused.xbrl", profile, "unused", None, None,
                         768 * 1024 * 1024, directory, 1, deadline, scratch)

if __name__ == "__main__":
    directory, reason = sys.argv[1:]
    context = multiprocessing.get_context("spawn")
    deadline = datetime.now(timezone.utc) + timedelta(seconds=4 if reason == "deadline" else 30)
    output = tempfile.TemporaryFile()
    result_file = Connection(os.dup(output.fileno()))
    scratch = tempfile.TemporaryDirectory(prefix="fundamental-parser-worker-")
    worker = context.Process(target=run_worker, args=(result_file, directory, deadline, scratch.name))
    worker.start()
    until = time.monotonic() + 15
    while not Path(directory, "serializing").exists() and worker.is_alive():
        if time.monotonic() >= until: raise RuntimeError("worker did not reach result serialization")
        time.sleep(0.01)
    assert Path(directory, "serializing").is_file()
    print(json.dumps({"worker_pid": worker.pid, "serialization_pending": worker.is_alive()}), flush=True)
    worker.join(timeout=20)
    print(json.dumps({"worker_exitcode": worker.exitcode}), flush=True)
""")
    directory = tmp_path / "slots"
    directory.mkdir(mode=0o700)
    edgar = directory / "edgar"
    edgar.mkdir()
    retained_source = edgar / "retained-plugin.py"
    retained_source.write_text("retained deployment asset")
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    process = subprocess.Popen(
        [sys.executable, str(script), str(directory), end_reason],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": str(temporary),
        },
    )
    try:
        assert process.stdout is not None
        assert select.select([process.stdout], [], [], 15)[0]
        observation = json.loads(process.stdout.readline())
        assert observation["serialization_pending"]
        with pytest.raises(ArelleParserError) as failure:
            _parse(directory)
        assert failure.value.code == "PARSER_CONCURRENCY_EXHAUSTED"
        if end_reason == "parent_exit":
            process.kill()
            process.wait(timeout=5)
        else:
            out, err = process.communicate(timeout=15)
            assert process.returncode == 0, err
            assert json.loads(out)["worker_exitcode"] == 124
        assert _parse(directory).facts
        assert not tuple(temporary.iterdir())
        assert retained_source.read_text() == "retained deployment asset"
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
