from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from validate_acceptance_manifest import emit_preflight_env, validate_manifest


def _manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "issue": 355,
        "status": "WIP",
        "branch": "codex/issue-355-forward-reference",
        "commit": "f" * 40,
        "sec_identity_required": True,
        "runtime": {
            "worktree": "/tmp/value-investment-agent",
            "browser_session": "run-1",
            "allowed_untracked_paths": [],
            "app": {
                "compose_project": "app-project",
                "compose_files": ["docker-compose.yml"],
                "env_file": "/tmp/app.env",
                "env_file_sha256": "a" * 64,
                "service": "backend",
                "container_port": 8000,
                "published_port": 18880,
                "url": "http://127.0.0.1:18880",
            },
            "fundamental": {
                "compose_project": "fundamental-project",
                "compose_files": [
                    "compose/verification/docker-compose.issue280-operations.yml",
                    "compose/verification/docker-compose.issue312-sec-ingestion.yml",
                ],
                "env_file": "/tmp/fundamental.env",
                "env_file_sha256": "b" * 64,
                "service": "fundamental-service",
                "container_port": 8080,
                "published_port": 18890,
                "url": "http://127.0.0.1:18890",
            },
        },
        "readiness": {
            "status": "ready",
            "capabilities": {"identity_resolution_configured": True},
        },
        "checks": [{"name": "health", "status": "pass", "command": "curl"}],
        "blockers": ["still WIP"],
        "next_step": "run acceptance",
    }


def test_valid_manifest_has_no_errors() -> None:
    assert validate_manifest(_manifest(), expected_issue=355) == []


def test_manifest_rejects_port_mismatch() -> None:
    manifest = _manifest()
    fundamental = manifest["runtime"]["fundamental"]  # type: ignore[index]
    fundamental["url"] = "http://127.0.0.1:18690"
    errors = validate_manifest(manifest, expected_issue=355)
    assert any("published_port" in error for error in errors)


def test_verified_manifest_requires_exact_commit_and_clean_checks() -> None:
    manifest = _manifest()
    manifest["status"] = "VERIFIED"
    manifest["blockers"] = []
    manifest["checks"][0]["status"] = "pass"  # type: ignore[index]
    errors = validate_manifest(manifest, expected_commit="e" * 40, expected_issue=355)
    assert any("does not match expected commit" in error for error in errors)


def test_sec_requirement_rejects_missing_capability() -> None:
    manifest = _manifest()
    manifest["readiness"]["capabilities"]["identity_resolution_configured"] = False  # type: ignore[index]
    errors = validate_manifest(manifest, expected_issue=355, require_sec_identity=True)
    assert any("identity_resolution_configured=true" in error for error in errors)


def test_emit_preflight_env_is_tab_delimited(capsys) -> None:
    emit_preflight_env(_manifest())
    output = capsys.readouterr().out
    assert "EXPECTED_COMMIT\t" in output
    assert "FUNDAMENTAL_COMPOSE_FILES\t" in output
