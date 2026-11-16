from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

import acceptance_service_preflight as preflight
import validate_issue_acceptance_policy as policy
from test_validate_acceptance_manifest import service_manifest
from validate_acceptance_manifest import acceptance_metadata_path


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
