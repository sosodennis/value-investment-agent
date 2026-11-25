from __future__ import annotations

import os
import subprocess
import sys

import pytest

import test_fiscal_history_recovery as recovery_cases
from test_fiscal_history_recovery import _seed_backup, target_pin

databases = recovery_cases.databases


@pytest.mark.parametrize(
    ("location", "substitution"),
    [
        ("authorization", "before_restore"),
        ("manifest", "before_restore"),
        ("table", "before_restore"),
        ("content", "before_restore"),
        ("table", "after_verification"),
        ("content", "after_verification"),
    ],
)
def test_restore_refuses_fifo_without_exceeding_original_deadline(
    databases, tmp_path, location, substitution
):
    source, target, _ = databases
    bundle, manifest = _seed_backup(source, tmp_path)
    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        path = {
            "authorization": pin,
            "manifest": bundle / "manifest.json",
            "table": bundle / manifest.tables[0].file.path,
            "content": bundle / manifest.objects[0].path,
        }[location]
        if substitution == "before_restore":
            path.rename(tmp_path / "retained-synthetic-file")
            os.mkfifo(path, 0o600)
        script = r"""
import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from fundamental_service import persistence_recovery as recovery
if sys.argv[7] == "after_verification":
    verify = recovery._verify_bundle
    def replace_after_verification(*args, **kwargs):
        result = verify(*args, **kwargs)
        path = Path(sys.argv[6])
        path.rename(path.with_suffix(".retained"))
        os.mkfifo(path, 0o600)
        print("SYNTHETIC_FILE_SUBSTITUTED", flush=True)
        return result
    recovery._verify_bundle = replace_after_verification
try:
    asyncio.run(recovery.restore_backup(
        sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]),
        authorization_path=Path(sys.argv[4]), manifest_digest=sys.argv[5],
        deadline_at=datetime.now(UTC) + timedelta(milliseconds=250),
    ))
except recovery.RecoveryError as error:
    print(str(error), flush=True)
    raise SystemExit(2)
"""
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                target,
                str(tmp_path / "target"),
                str(bundle),
                str(pin),
                manifest.digest,
                str(path),
                substitution,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=2.5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=2)
            pytest.fail(
                f"restore blocked on a synthetic FIFO beyond its original deadline: {stdout} {stderr}"
            )
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)
        assert process.returncode == 2, (stdout, stderr)
        if substitution == "after_verification":
            assert "SYNTHETIC_FILE_SUBSTITUTED" in stdout
            assert (
                "regular files" in stdout
                or "persistence recovery deadline exceeded" in stdout
            ), (stdout, stderr)
        else:
            assert "regular files" in stdout, (stdout, stderr)


@pytest.mark.parametrize("boundary", ["rows", "file-record"])
def test_row_and_hash_reader_refuse_fifo_at_their_descriptor_boundary(
    tmp_path, boundary
):
    script = r"""
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from fundamental_service import persistence_recovery as recovery
path = Path(sys.argv[1])
os.mkfifo(path, 0o600)
token = recovery._OPERATION_DEADLINE.set(datetime.now(UTC) + timedelta(milliseconds=250))
try:
    if sys.argv[2] == "rows":
        table = recovery.BackupTableV1(
            name="schema_migrations", columns=("version",), row_count=0,
            file=recovery.BackupFileV1(path=path.name, digest="0" * 64, byte_length=0),
        )
        tuple(recovery._rows(path.parent, table))
    else:
        recovery._file_record(path, path.parent)
except recovery.RecoveryError as error:
    print(str(error), flush=True)
    raise SystemExit(2)
finally:
    recovery._OPERATION_DEADLINE.reset(token)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path / "synthetic.fifo"), boundary],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=2.5)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=2)
        pytest.fail(f"filesystem reader blocked on synthetic FIFO: {stdout} {stderr}")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
    assert process.returncode == 2, (stdout, stderr)
    assert "regular files" in stdout, (stdout, stderr)
