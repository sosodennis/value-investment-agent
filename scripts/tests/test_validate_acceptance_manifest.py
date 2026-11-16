from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from validate_acceptance_manifest import (
    VALUATION_FLOW_CHECKS,
    VALUATION_FLOW_PROFILE,
    emit_preflight_env,
    validate_manifest,
)


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


def service_manifest():
    manifest = _manifest()
    manifest.update(
        schema_version=2,
        acceptance_scope="fundamental-service",
        acceptance_profile=VALUATION_FLOW_PROFILE,
        issue=361,
    )
    runtime = manifest["runtime"]
    del runtime["app"]
    del runtime["browser_session"]
    service = runtime["fundamental"]
    service["env_files"] = [
        {"path": service.pop("env_file"), "sha256": service.pop("env_file_sha256")}
    ]
    service.update(
        published_host="127.0.0.1",
        image_id="sha256:" + "c" * 64,
        source={
            "repository_path": "fundamental-service/src/fundamental_service",
            "container_path": "/app/src/fundamental_service",
            "sha256": "d" * 64,
            "file_count": 53,
        },
        runtime_pins={
            "python": "3.12.16",
            "arelle-release": "2.47.4",
            "pydantic": "2.14.2",
        },
        dependencies=[
            {
                "service": "fundamental-postgres",
                "published_host": "127.0.0.1",
                "container_port": 5432,
                "published_port": 18891,
            }
        ],
        networks=["fundamental-project_default"],
        volumes=["fundamental-project_data"],
    )
    manifest["checks"] = [
        {"name": name, "command": "pending", "status": "not_run"}
        for name in sorted(VALUATION_FLOW_CHECKS)
    ]
    return manifest


def test_service_scope_does_not_require_app_or_browser(capsys) -> None:
    manifest = service_manifest()
    assert (
        validate_manifest(manifest, expected_issue=361, require_sec_identity=True) == []
    )
    emit_preflight_env(manifest)
    assert capsys.readouterr().out == "ACCEPTANCE_SCOPE\tfundamental-service\n"


def test_service_scope_cannot_silently_downgrade_app_contract() -> None:
    manifest = _manifest()
    manifest["schema_version"] = 2
    manifest["acceptance_scope"] = "fundamental-service"
    assert any(
        "cannot contain app or browser" in error
        for error in validate_manifest(manifest)
    )


def test_service_scope_requires_source_runtime_and_owned_resources() -> None:
    for key in (
        "source",
        "image_id",
        "runtime_pins",
        "env_files",
        "dependencies",
        "networks",
        "volumes",
    ):
        manifest = deepcopy(service_manifest())
        del manifest["runtime"]["fundamental"][key]
        assert any(key in error for error in validate_manifest(manifest)), key


def test_service_verification_requires_complete_valuation_flow_checks() -> None:
    manifest = service_manifest()
    manifest.update(status="VERIFIED", blockers=[])
    assert any("every check" in error for error in validate_manifest(manifest))
    manifest["checks"] = []
    assert any(
        "missing persistent valuation flow checks" in error
        for error in validate_manifest(manifest)
    )


def test_research_checks_cannot_verify_the_revised_delivery_scope() -> None:
    manifest = service_manifest()
    manifest.update(status="VERIFIED", blockers=[])
    manifest["checks"] = [
        {
            "name": name,
            "command": "old research check",
            "status": "pass",
            "commit": manifest["commit"],
            "input_digest": "a" * 64,
            "output_digest": "b" * 64,
            "exit_code": 0,
        }
        for name in (
            "mapping",
            "history_replay",
            "forecast",
            "label",
            "deterministic_replay",
            "failure_retention",
            "architecture",
            "ruff",
            "types",
            "diff",
            "service_acceptance",
            "full_replay_repeat",
            "review",
        )
    ]
    errors = validate_manifest(manifest)
    assert any("source_reuse" in error for error in errors)
    assert any("restart_restore" in error for error in errors)
    assert any("calculation" in error for error in errors)


def test_service_scope_requires_its_declared_valuation_flow_profile() -> None:
    manifest = service_manifest()
    del manifest["acceptance_profile"]
    assert any("acceptance_profile" in error for error in validate_manifest(manifest))
    manifest["acceptance_profile"] = "historical-threshold-research"
    assert any("acceptance_profile" in error for error in validate_manifest(manifest))


def test_service_passing_checks_require_exact_commit_and_digests() -> None:
    manifest = service_manifest()
    check = manifest["checks"][0]
    check.update(status="pass", commit="e" * 40, exit_code=0)
    errors = validate_manifest(manifest)
    assert any("commit must match" in error for error in errors)
    assert any("input_digest" in error for error in errors)
    assert any("output_digest" in error for error in errors)
