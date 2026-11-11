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
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SENSITIVE_KEY_RE = re.compile(
    r"(?:secret|token|password|api[_-]?key|private[_-]?key)", re.IGNORECASE
)
STATUSES = {"WIP", "BLOCKED", "VERIFIED"}
CHECK_STATUSES = {"pass", "fail", "not_run"}
REPLAY_CHECKS = {
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
}


def acceptance_metadata_path(path: str, issue: int) -> bool:
    if issue == 361:
        return (
            bool(
                re.fullmatch(
                    r"docs/acceptance/issue-361-[a-zA-Z0-9_./-]+\.(?:md|json|json\.gz)",
                    path,
                )
            )
            and ".." not in Path(path).parts
        )
    return path in {
        f"docs/acceptance/issue-{issue}-runtime.json",
        f"docs/acceptance/issue-{issue}-acceptance.md",
    } or bool(re.fullmatch(rf"docs/acceptance/issue-{issue}-progress-.+\.md", path))


def _digest(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        errors.append(f"{path} must be a 64-character lowercase SHA-256")


def _service_evidence(service: dict[str, Any], errors: list[str]) -> None:
    prefix = "runtime.fundamental"
    if service.get("published_host") not in {"127.0.0.1", "0.0.0.0", "[::1]", "[::]"}:
        errors.append(f"{prefix}.published_host must record the local Docker binding")
    env_files = service.get("env_files")
    if not isinstance(env_files, list) or not env_files:
        errors.append(f"{prefix}.env_files must be a non-empty ordered list")
    else:
        paths = []
        for index, entry in enumerate(env_files):
            path = f"{prefix}.env_files[{index}]"
            if not isinstance(entry, dict):
                errors.append(f"{path} must be an object")
                continue
            paths.append(_string(entry.get("path"), f"{path}.path", errors))
            _digest(entry.get("sha256"), f"{path}.sha256", errors)
        if len(paths) != len(set(paths)):
            errors.append(f"{prefix}.env_files contains duplicate paths")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(service.get("image_id", ""))):
        errors.append(f"{prefix}.image_id must pin a Docker image SHA-256")
    source = service.get("source")
    if not isinstance(source, dict):
        errors.append(f"{prefix}.source must be an object")
    else:
        # This scope checks the installed Fundamental Python package against Git.
        for key, expected in {
            "repository_path": "fundamental-service/src/fundamental_service",
            "container_path": "/app/src/fundamental_service",
        }.items():
            if source.get(key) != expected:
                errors.append(f"{prefix}.source.{key} must be {expected}")
        _digest(source.get("sha256"), f"{prefix}.source.sha256", errors)
        _positive_int(source.get("file_count"), f"{prefix}.source.file_count", errors)
    pins = service.get("runtime_pins")
    if not isinstance(pins, dict) or set(pins) != {
        "python",
        "arelle-release",
        "pydantic",
    }:
        errors.append(
            f"{prefix}.runtime_pins must pin python, arelle-release and pydantic"
        )
    else:
        for name, value in pins.items():
            _string(value, f"{prefix}.runtime_pins.{name}", errors)
    dependencies = service.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        errors.append(f"{prefix}.dependencies must list required healthy services")
    else:
        for index, dependency in enumerate(dependencies):
            path = f"{prefix}.dependencies[{index}]"
            if not isinstance(dependency, dict):
                errors.append(f"{path} must be an object")
                continue
            _string(dependency.get("service"), f"{path}.service", errors)
            if dependency.get("published_host") not in {
                "127.0.0.1",
                "0.0.0.0",
                "[::1]",
                "[::]",
            }:
                errors.append(
                    f"{path}.published_host must record the local Docker binding"
                )
            for key in ("container_port", "published_port"):
                _positive_int(dependency.get(key), f"{path}.{key}", errors)
    for key in ("networks", "volumes"):
        values = service.get(key)
        if (
            not isinstance(values, list)
            or not values
            or any(
                not isinstance(value, str)
                or not value.startswith(str(service.get("compose_project")) + "_")
                for value in values
            )
        ):
            errors.append(f"{prefix}.{key} must list project-owned resource names")


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
    runtime: dict[str, Any], name: str, errors: list[str], *, service_only: bool = False
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
    env_file = (
        None
        if service_only
        else _string(
            _required(service, "env_file", f"runtime.{name}", errors),
            f"runtime.{name}.env_file",
            errors,
        )
    )
    env_file_sha256 = (
        None
        if service_only
        else _string(
            _required(service, "env_file_sha256", f"runtime.{name}", errors),
            f"runtime.{name}.env_file_sha256",
            errors,
        )
    )
    if env_file_sha256 is not None and not SHA256_RE.fullmatch(env_file_sha256):
        errors.append(
            f"runtime.{name}.env_file_sha256 must be a 64-character lowercase SHA-256"
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
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            errors.append(f"runtime.{name}.url must be a valid HTTP URL")
            parsed = urlsplit("")
            port = None
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            errors.append(f"runtime.{name}.url must be an HTTP URL with a hostname")
        elif port != published_port:
            errors.append(
                f"runtime.{name}.url port {port} does not match "
                f"published_port {published_port}"
            )

        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            errors.append(
                f"runtime.{name}.url cannot contain credentials, query or fragment"
            )
        if service_only and (
            parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.path not in {"", "/"}
        ):
            errors.append(f"runtime.{name}.url must use the local service root")

    if service_only:
        _service_evidence(service, errors)

    return {
        "compose_project": compose_project,
        "env_file": env_file,
        "env_file_sha256": env_file_sha256,
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
    service_only = manifest.get("schema_version") == 2
    if manifest.get("schema_version") not in {1, 2}:
        errors.append("schema_version must be 1 or 2")
    if service_only and manifest.get("acceptance_scope") != "fundamental-service":
        errors.append("schema_version 2 requires acceptance_scope=fundamental-service")
    if not service_only and "acceptance_scope" in manifest:
        errors.append("schema_version 1 retains the app and browser acceptance scope")

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
    if service_only:
        if "app" in runtime or "browser_session" in runtime:
            errors.append(
                "fundamental-service scope cannot contain app or browser_session"
            )
    else:
        _string(runtime.get("browser_session"), "runtime.browser_session", errors)
        _validate_service(runtime, "app", errors)
    fundamental = _validate_service(
        runtime, "fundamental", errors, service_only=service_only
    )

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
        if service_only and check_status == "pass":
            if check.get("commit") != commit:
                errors.append(f"{path}.commit must match the tested manifest commit")
            for key in ("input_digest", "output_digest"):
                _digest(check.get(key), f"{path}.{key}", errors)
            exit_code = check.get("exit_code")
            if (
                not isinstance(exit_code, int)
                or isinstance(exit_code, bool)
                or exit_code != 0
            ):
                errors.append(f"{path}.exit_code must be 0 for a passing check")

    if service_only:
        names = [check.get("name") for check in checks if isinstance(check, dict)]
        if len(names) != len(set(str(name) for name in names)):
            errors.append("checks must have unique names")
        missing = REPLAY_CHECKS - set(str(name) for name in names)
        if missing:
            errors.append(
                f"missing history replay checks: {', '.join(sorted(missing))}"
            )

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
    if manifest.get("schema_version") == 2:
        print("ACCEPTANCE_SCOPE\tfundamental-service")
        return
    runtime = manifest["runtime"]
    app = runtime["app"]
    fundamental = runtime["fundamental"]
    values = {
        "EXPECTED_WORKTREE": runtime["worktree"],
        "EXPECTED_ISSUE": str(manifest["issue"]),
        "EXPECTED_BRANCH": manifest["branch"],
        "EXPECTED_COMMIT": manifest["commit"],
        "APP_COMPOSE_PROJECT": app["compose_project"],
        "APP_COMPOSE_FILES": ":".join(app["compose_files"]),
        "APP_ENV_FILE": app["env_file"],
        "APP_ENV_FILE_SHA256": app["env_file_sha256"],
        "APP_URL": app["url"],
        "APP_EXPECTED_PORT": str(app["published_port"]),
        "APP_SERVICE": app["service"],
        "APP_CONTAINER_PORT": str(app["container_port"]),
        "FUNDAMENTAL_COMPOSE_PROJECT": fundamental["compose_project"],
        "FUNDAMENTAL_COMPOSE_FILES": ":".join(fundamental["compose_files"]),
        "FUNDAMENTAL_ENV_FILE": fundamental["env_file"],
        "FUNDAMENTAL_ENV_FILE_SHA256": fundamental["env_file_sha256"],
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
