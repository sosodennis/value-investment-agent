"""Canonical field packets publish once and reject substituted identities."""

import json
import sys
from pathlib import Path

import pytest

from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_accounting_fields import request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import extract_accounting_fields as cli  # noqa: E402

HEAD = "c" * 40


@pytest.fixture
def invocation(tmp_path, monkeypatch):
    supplied = request()
    path = tmp_path / "request.json"
    path.write_bytes(canonical_bytes(supplied))
    artifacts = tmp_path / "artifacts"
    argv = [
        "extract_accounting_fields.py",
        "--request",
        str(path),
        "--request-digest",
        sha256_digest(supplied),
        "--exact-commit",
        HEAD,
        "--output-directory",
        str(artifacts),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(
        cli.subprocess,
        "check_output",
        lambda args, **_: HEAD if args[1] == "rev-parse" else "",
    )
    return path, artifacts, argv


def test_second_command_reuses_artifact_without_rewrite(invocation, capsys):
    _, artifacts, _ = invocation
    assert cli.main() == 0
    first = json.loads(capsys.readouterr().out)
    path = artifacts / f"{first['report_digest']}.json"
    before = path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_size
    assert first["wrote"] is True and first["candidate_count"] == 1
    assert cli.main() == 0
    second = json.loads(capsys.readouterr().out)
    assert second == {**first, "wrote": False}
    assert before == (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_size)
    assert len(tuple(artifacts.glob("*.json"))) == 1


@pytest.mark.parametrize("mutation", ["request", "commit", "dirty", "corrupt_artifact"])
def test_invalid_inputs_or_existing_artifact_are_not_overwritten(
    invocation, monkeypatch, capsys, mutation
):
    path, artifacts, argv = invocation
    if mutation == "request":
        path.write_bytes(b"{}")
    elif mutation == "commit":
        argv[argv.index(HEAD)] = "d" * 40
    elif mutation == "dirty":
        monkeypatch.setattr(
            cli.subprocess,
            "check_output",
            lambda args, **_: HEAD if args[1] == "rev-parse" else " M source.py",
        )
    else:
        assert cli.main() == 0
        receipt = json.loads(capsys.readouterr().out)
        path = artifacts / f"{receipt['report_digest']}.json"
        path.write_bytes(b"corrupt retained artifact")
    with pytest.raises(SystemExit) as failure:
        cli.main()
    assert failure.value.code == 2
    if mutation == "corrupt_artifact":
        assert path.read_bytes() == b"corrupt retained artifact"
    else:
        assert not artifacts.exists()
