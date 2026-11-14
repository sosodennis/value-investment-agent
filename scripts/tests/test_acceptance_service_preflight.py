from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

import acceptance_service_preflight as preflight
import validate_issue_acceptance_policy as policy
from test_validate_acceptance_manifest import service_manifest
from validate_acceptance_manifest import acceptance_metadata_path


@pytest.mark.parametrize("resource", ["taxonomy", "edgar", "xule", "dqc", "catalog"])
@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_fresh_runtime_check_rejects_changed_sec_resources(tmp_path, resource, damage):
    from fundamental_service.arelle_parser import _directory_hash

    assets = {}
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("FUNDAMENTAL_")
    }
    root = Path(__file__).parents[2]
    env.update(
        PYTHONPATH=os.pathsep.join(
            str(root / path)
            for path in ("fundamental-service/src", "finance-agent-core")
        ),
        PYTHONDONTWRITEBYTECODE="1",
        FUNDAMENTAL_SERVICE_TOKEN="preflight-test-token",
        FUNDAMENTAL_SERVICE_DATA_ROOT=str(tmp_path / "data"),
        FUNDAMENTAL_SERVICE_DATABASE_URL="postgresql+asyncpg://fixture:fixture@127.0.0.1:9/fixture",
        FUNDAMENTAL_SEC_USER_AGENT="Preflight fixture fixture@example.test",
        FUNDAMENTAL_SEC_TAXONOMY_MANIFEST_ID="fixture-taxonomy",
        FUNDAMENTAL_SEC_TAXONOMY_VERSION="us-gaap-2025",
        FUNDAMENTAL_SEC_SUPPORTED_FILING_YEARS="2026",
        FUNDAMENTAL_SEC_SUPPORTED_FILING_FORMS="10-K",
    )
    for name, prefix in (
        ("taxonomy", "FUNDAMENTAL_SEC_TAXONOMY_CACHE"),
        ("edgar", "FUNDAMENTAL_SEC_EDGAR_PLUGIN"),
        ("xule", "FUNDAMENTAL_SEC_XULE_PLUGIN"),
    ):
        directory = tmp_path / name
        directory.mkdir()
        assets[name] = directory / "fixture.txt"
        assets[name].write_bytes(name.encode())
        env[prefix + "_DIR"] = str(directory)
        env[prefix + "_SHA256"] = _directory_hash(directory)
    for name in ("dqc", "catalog"):
        assets[name] = tmp_path / (name + ".zip")
        assets[name].write_bytes(name.encode())
    env["FUNDAMENTAL_SEC_DQC_RULESET_PATH"] = str(assets["dqc"])
    env["FUNDAMENTAL_SEC_DQC_RULESET_SHA256"] = hashlib.sha256(b"dqc").hexdigest()
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "bindings": [
                    {
                        "taxonomy_namespace": "http://fasb.org/us-gaap/2025",
                        "path": str(assets["catalog"]),
                        "sha256": hashlib.sha256(b"catalog").hexdigest(),
                    }
                ]
            }
        )
    )
    env["FUNDAMENTAL_SEC_DQC_RULESET_CATALOG_PATH"] = str(catalog)
    command = [sys.executable, "-c", preflight.CONTAINER_SEC_RESOURCES]
    before = subprocess.run(command, env=env, capture_output=True, timeout=30)
    assert before.returncode == 0, before.stderr.decode()
    pins = json.loads(before.stdout)
    assert pins["edgar_plugin_sha256"] == env["FUNDAMENTAL_SEC_EDGAR_PLUGIN_SHA256"]
    if damage == "missing":
        assets[resource].unlink()
    else:
        assets[resource].write_bytes(b"changed after startup")
    after = subprocess.run(command, env=env, capture_output=True, timeout=30)
    assert after.returncode != 0
    assert not after.stdout
    assert b"pinned" in after.stderr


def test_content_addressed_report_repeat_preserves_bytes_and_mtime(tmp_path):
    report = {"commit": "f" * 40, "input_digest": "a" * 64, "output_digest": "b" * 64}
    first = preflight.publish(tmp_path, report)
    path = Path(first["path"])
    before = path.stat().st_mtime_ns
    second = preflight.publish(tmp_path, report)
    assert first["sha256"] == second["sha256"]
    assert first["wrote"] is True and second["wrote"] is False
    assert path.stat().st_mtime_ns == before
    assert list(tmp_path.iterdir()) == [path]
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="content digest"):
        preflight.publish(tmp_path, report)


def test_service_policy_gates_361_without_weakening_previous_scopes(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs/acceptance").mkdir(parents=True)
    path = tmp_path / "docs/acceptance/issue-361-runtime.json"
    manifest = service_manifest()
    manifest["branch"] = "codex/issue-361-replay-evidence"
    path.write_text(json.dumps(manifest))
    event = tmp_path / "event.json"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_HEAD_REF", "codex/issue-361-replay-evidence")
    for draft, body, expected in [
        (True, "Refs #361", 0),
        (False, "Refs #361", 1),
        (True, "Closes #361", 1),
    ]:
        event.write_text(json.dumps({"pull_request": {"draft": draft, "body": body}}))
        assert policy.main() == expected
    assert "outside fundamental sequence" not in capsys.readouterr().out
    monkeypatch.setenv("GITHUB_HEAD_REF", "codex/issue-355-forward-reference")
    legacy = service_manifest()
    legacy["issue"] = 355
    (path.parent / "issue-355-runtime.json").write_text(json.dumps(legacy))
    assert policy.main() == 1
    assert "schema_version=1" in capsys.readouterr().err


def test_post_verification_metadata_cannot_include_code_or_other_issues():
    assert acceptance_metadata_path(
        "docs/acceptance/issue-361-evidence/report/abc.json.gz", 361
    )
    assert not acceptance_metadata_path(
        "docs/acceptance/issue-361-evidence/helper.py", 361
    )
    assert not acceptance_metadata_path("docs/acceptance/issue-355-acceptance.md", 361)
    assert not acceptance_metadata_path(
        "docs/acceptance/issue-361-evidence/../other.md", 361
    )
    assert not acceptance_metadata_path(
        "docs/acceptance/issue-355-evidence/report/abc.json.gz", 355
    )


def test_git_gate_rejects_implementation_changes_and_dirty_tree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def git(*args):
        return subprocess.check_output(
            ["git", *args], stderr=subprocess.DEVNULL, text=True
        ).strip()

    git("init", "-b", "codex/issue-361-test")
    git("config", "user.email", "fixture@example.test")
    git("config", "user.name", "Fixture")
    (tmp_path / "source.py").write_text("pass\n")
    git("add", ".")
    git("commit", "-m", "base")
    base = git("rev-parse", "HEAD")
    manifest = service_manifest()
    manifest.update(branch="codex/issue-361-test", commit=base)
    manifest["runtime"]["worktree"] = str(tmp_path)
    assert preflight.check_git(manifest, []) == base
    (tmp_path / "source.py").write_text("raise RuntimeError\n")
    with pytest.raises(ValueError, match="command failed"):
        preflight.check_git(manifest, [])
    git("add", ".")
    git("commit", "-m", "implementation")
    with pytest.raises(ValueError, match="implementation files"):
        preflight.check_git(manifest, [])


def test_running_service_requires_exact_config_health_project_and_binding(monkeypatch):
    service = service_manifest()["runtime"]["fundamental"]
    container = {
        "Config": {
            "Labels": {
                "com.docker.compose.project": service["compose_project"],
                "com.docker.compose.service": service["service"],
                "com.docker.compose.config-hash": "a" * 64,
            }
        },
        "State": {"Running": True, "Health": {"Status": "healthy"}},
    }
    binding = "127.0.0.1:18890"

    def run(command, results):
        if command[:2] == ["docker", "inspect"]:
            return json.dumps([container]).encode()
        if "--hash" in command:
            return f"fundamental-service {'a' * 64}".encode()
        if "port" in command:
            return binding.encode()
        return b"fixture-fundamental-service-1\n"

    monkeypatch.setattr(preflight, "run", run)
    assert (
        preflight.check_container(service, service, ["docker", "compose"], [])[0]
        == "fixture-fundamental-service-1"
    )
    binding = "0.0.0.0:18890"
    with pytest.raises(ValueError, match="recorded host and port"):
        preflight.check_container(service, service, ["docker", "compose"], [])
    binding = "127.0.0.1:18890"
    container["Config"]["Labels"]["com.docker.compose.config-hash"] = "b" * 64
    with pytest.raises(ValueError, match="different Compose configuration"):
        preflight.check_container(service, service, ["docker", "compose"], [])
    container["Config"]["Labels"]["com.docker.compose.config-hash"] = "a" * 64
    container["State"]["Health"]["Status"] = "starting"
    with pytest.raises(ValueError, match="not healthy"):
        preflight.check_container(service, service, ["docker", "compose"], [])
