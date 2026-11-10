#!/usr/bin/env python3
"""Validate the machine-readable runtime tuple used for issue acceptance."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SENSITIVE_KEY_RE = re.compile(
    r"(?:secret|token|password|api[_-]?key|private[_-]?key)", re.IGNORECASE
)
STATUSES = {"WIP", "BLOCKED", "VERIFIED"}
CHECK_STATUSES = {"pass", "fail", "not_run"}


def _required(mapping: dict[str, Any], key: str, path: str, errors: list[str]) -> Any:
    if key not in mapping:
        errors.append(f"missing {path}.{key}")
        return None
    return mapping[key]


def _string(value: Any, path: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path} must be a non-empty string")
        return None
    return value


def _positive_int(value: Any, path: str, errors: list[str]) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        errors.append(f"{path} must be a positive integer")
        return None
    return value


def _sensitive_keys(value: Any, path: str = "manifest") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if SENSITIVE_KEY_RE.search(str(key)):
                found.append(child_path)
            found.extend(_sensitive_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_sensitive_keys(child, f"{path}[{index}]"))
    return found


def _validate_service(
    runtime: dict[str, Any], name: str, errors: list[str]
) -> dict[str, Any] | None:
    service = _required(runtime, name, "runtime", errors)
    if not isinstance(service, dict):
        errors.append(f"runtime.{name} must be an object")
        return None

    compose_project = _string(
        _required(service, "compose_project", f"runtime.{name}", errors),
        f"runtime.{name}.compose_project",
        errors,
    )
    env_file = _string(
        _required(service, "env_file", f"runtime.{name}", errors),
        f"runtime.{name}.env_file",
        errors,
    )
    service_name = _string(
        _required(service, "service", f"runtime.{name}", errors),
        f"runtime.{name}.service",
        errors,
    )
    url = _string(
        _required(service, "url", f"runtime.{name}", errors),
        f"runtime.{name}.url",
        errors,
    )
    container_port = _positive_int(
        _required(service, "container_port", f"runtime.{name}", errors),
        f"runtime.{name}.container_port",
        errors,
    )
    published_port = _positive_int(
        _required(service, "published_port", f"runtime.{name}", errors),
        f"runtime.{name}.published_port",
        errors,
    )
    compose_files = _required(service, "compose_files", f"runtime.{name}", errors)
    if not isinstance(compose_files, list) or not compose_files:
        errors.append(f"runtime.{name}.compose_files must be a non-empty list")
        compose_files = []
    else:
        for index, compose_file in enumerate(compose_files):
            _string(compose_file, f"runtime.{name}.compose_files[{index}]", errors)

    if url is not None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            errors.append(f"runtime.{name}.url must be an HTTP URL with a hostname")
        elif parsed.port != published_port:
            errors.append(
                f"runtime.{name}.url port {parsed.port} does not match "
                f"published_port {published_port}"
            )

    return {
        "compose_project": compose_project,
        "env_file": env_file,
        "service": service_name,
        "url": url,
        "container_port": container_port,
        "published_port": published_port,
        "compose_files": compose_files,
    }


def validate_manifest(
    manifest: dict[str, Any],
    *,
    expected_commit: str | None = None,
    expected_issue: int | None = None,
    require_sec_identity: bool = False,
) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    issue = manifest.get("issue")
    if not isinstance(issue, int) or isinstance(issue, bool) or issue <= 0:
        errors.append("issue must be a positive integer")
    elif expected_issue is not None and issue != expected_issue:
        errors.append(f"issue {issue} does not match expected issue {expected_issue}")

    status = manifest.get("status")
    if status not in STATUSES:
        errors.append(f"status must be one of {sorted(STATUSES)}")

    _string(manifest.get("branch"), "branch", errors)
    commit = _string(manifest.get("commit"), "commit", errors)
    if commit is not None and not COMMIT_RE.fullmatch(commit):
        errors.append("commit must be a full 40-character lowercase SHA")
    if expected_commit is not None and commit != expected_commit:
        errors.append(
            f"commit {commit} does not match expected commit {expected_commit}"
        )

    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict):
        errors.append("runtime must be an object")
        runtime = {}
    _string(runtime.get("worktree"), "runtime.worktree", errors)
    _string(runtime.get("browser_session"), "runtime.browser_session", errors)
    _validate_service(runtime, "app", errors)
    fundamental = _validate_service(runtime, "fundamental", errors)

    allowed_untracked = runtime.get("allowed_untracked_paths", [])
    if not isinstance(allowed_untracked, list) or any(
        not isinstance(item, str) or not item.strip() for item in allowed_untracked
    ):
        errors.append("runtime.allowed_untracked_paths must be a list of strings")

    readiness = manifest.get("readiness")
    if not isinstance(readiness, dict):
        errors.append("readiness must be an object")
        readiness = {}
    readiness_status = readiness.get("status")
    if readiness_status not in {"ready", "not_ready", "not_run"}:
        errors.append("readiness.status must be ready, not_ready, or not_run")
    capabilities = readiness.get("capabilities", {})
    if not isinstance(capabilities, dict):
        errors.append("readiness.capabilities must be an object")
        capabilities = {}

    sec_required = bool(manifest.get("sec_identity_required")) or require_sec_identity
    if sec_required:
        if not isinstance(fundamental, dict) or not any(
            str(path).endswith("docker-compose.issue312-sec-ingestion.yml")
            for path in fundamental.get("compose_files", [])
        ):
            errors.append(
                "SEC-backed acceptance requires docker-compose.issue312-sec-ingestion.yml"
            )
        if capabilities.get("identity_resolution_configured") is not True:
            errors.append(
                "SEC-backed acceptance requires readiness capability "
                "identity_resolution_configured=true"
            )

    checks = manifest.get("checks")
    if not isinstance(checks, list):
        errors.append("checks must be a list")
        checks = []
    for index, check in enumerate(checks):
        path = f"checks[{index}]"
        if not isinstance(check, dict):
            errors.append(f"{path} must be an object")
            continue
        _string(check.get("name"), f"{path}.name", errors)
        check_status = check.get("status")
        if check_status not in CHECK_STATUSES:
            errors.append(f"{path}.status must be one of {sorted(CHECK_STATUSES)}")
        _string(check.get("command"), f"{path}.command", errors)

    blockers = manifest.get("blockers", [])
    if not isinstance(blockers, list) or any(
        not isinstance(item, str) or not item.strip() for item in blockers
    ):
        errors.append("blockers must be a list of strings")
        blockers = []
    _string(manifest.get("next_step"), "next_step", errors)

    if status == "VERIFIED":
        if blockers:
            errors.append("VERIFIED manifest cannot contain blockers")
        if any(
            check.get("status") != "pass" for check in checks if isinstance(check, dict)
        ):
            errors.append("VERIFIED manifest requires every check to have status=pass")
        if readiness_status != "ready":
            errors.append("VERIFIED manifest requires readiness.status=ready")
        if expected_commit is None:
            errors.append("VERIFIED validation requires --expected-commit")

    for path in _sensitive_keys(manifest):
        errors.append(f"sensitive field is not allowed in acceptance manifest: {path}")

    return errors


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TypeError("manifest root must be an object")
    return value


def emit_preflight_env(manifest: dict[str, Any]) -> None:
    runtime = manifest["runtime"]
    app = runtime["app"]
    fundamental = runtime["fundamental"]
    values = {
        "EXPECTED_WORKTREE": runtime["worktree"],
        "EXPECTED_BRANCH": manifest["branch"],
        "EXPECTED_COMMIT": manifest["commit"],
        "APP_COMPOSE_PROJECT": app["compose_project"],
        "APP_COMPOSE_FILES": ":".join(app["compose_files"]),
        "APP_ENV_FILE": app["env_file"],
        "APP_URL": app["url"],
        "APP_EXPECTED_PORT": str(app["published_port"]),
        "APP_SERVICE": app["service"],
        "APP_CONTAINER_PORT": str(app["container_port"]),
        "FUNDAMENTAL_COMPOSE_PROJECT": fundamental["compose_project"],
        "FUNDAMENTAL_COMPOSE_FILES": ":".join(fundamental["compose_files"]),
        "FUNDAMENTAL_ENV_FILE": fundamental["env_file"],
        "FUNDAMENTAL_URL": fundamental["url"],
        "FUNDAMENTAL_EXPECTED_PORT": str(fundamental["published_port"]),
        "FUNDAMENTAL_SERVICE": fundamental["service"],
        "FUNDAMENTAL_CONTAINER_PORT": str(fundamental["container_port"]),
        "REQUIRE_SEC_IDENTITY_RESOLUTION": "1"
        if manifest.get("sec_identity_required")
        else "0",
        "ALLOWED_UNTRACKED_PATHS": ":".join(runtime.get("allowed_untracked_paths", [])),
    }
    for key, value in values.items():
        print(f"{key}\t{value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-issue", type=int)
    parser.add_argument("--require-sec-identity", action="store_true")
    parser.add_argument("--emit-preflight-env", action="store_true")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.path)
    except (TypeError, ValueError) as exc:
        print(f"acceptance manifest: FAIL: {exc}", file=sys.stderr)
        return 1

    errors = validate_manifest(
        manifest,
        expected_commit=args.expected_commit,
        expected_issue=args.expected_issue,
        require_sec_identity=args.require_sec_identity,
    )
    if errors:
        for error in errors:
            print(f"acceptance manifest: FAIL: {error}", file=sys.stderr)
        return 1

    if args.emit_preflight_env:
        emit_preflight_env(manifest)
    else:
        print(
            f"acceptance manifest: PASS issue={manifest['issue']} "
            f"status={manifest['status']} commit={manifest['commit']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
