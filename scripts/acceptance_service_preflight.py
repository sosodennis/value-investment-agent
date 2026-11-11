#!/usr/bin/env python3
"""Verify a Fundamental-only acceptance tuple without starting an app/browser."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from validate_acceptance_manifest import (
    acceptance_metadata_path,
    load_manifest,
    validate_manifest,
)
from validate_compose_inputs import validate as validate_compose_inputs


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def publish(directory: Path, report: dict[str, Any]) -> dict[str, Any]:
    data = canonical(report)
    sha = hashlib.sha256(data).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{sha}.json"
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("existing report bytes do not match its content digest")
        return {"path": str(path), "sha256": sha, "wrote": False}
    fd, temporary = tempfile.mkstemp(prefix=".preflight-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"path": str(path), "sha256": sha, "wrote": True}


def run(command: list[str], results: list[dict[str, Any]]) -> bytes:
    result = subprocess.run(command, capture_output=True, check=False)
    # Docker inspect includes secrets and changing healthcheck timestamps.
    # The report keeps exit codes and the stable fields verified below.
    results.append(
        {
            "command": command,
            "exit_code": result.returncode,
        }
    )
    if result.returncode:
        raise ValueError(f"command failed (exit {result.returncode}): {command[0]}")
    return result.stdout


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check_git(manifest: dict[str, Any], results: list[dict[str, Any]]) -> str:
    runtime = manifest["runtime"]
    root = Path(run(["git", "rev-parse", "--show-toplevel"], results).decode().strip())
    require(
        root.resolve() == Path(runtime["worktree"]).resolve() == Path.cwd().resolve(),
        "run from the recorded Git worktree root",
    )
    branch = (
        run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], results)
        .decode()
        .strip()
    )
    require(branch == manifest["branch"], "branch differs from runtime tuple")
    head = run(["git", "rev-parse", "HEAD"], results).decode().strip()
    commit = manifest["commit"]
    run(["git", "merge-base", "--is-ancestor", commit, head], results)
    changed = (
        run(["git", "diff", "--name-only", f"{commit}..{head}"], results)
        .decode()
        .splitlines()
    )
    require(
        all(acceptance_metadata_path(path, manifest["issue"]) for path in changed),
        "post-verification commit changes implementation files",
    )
    run(["git", "diff", "--quiet"], results)
    run(["git", "diff", "--cached", "--quiet"], results)
    untracked = run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], results
    )
    allowed = set(runtime.get("allowed_untracked_paths", []))
    require(
        all(path.decode() in allowed for path in untracked.split(b"\0") if path),
        "untracked path is not explicitly allowed",
    )
    return head


def source_files(
    commit: str, source: dict[str, Any], results: list[dict[str, Any]]
) -> dict[str, str]:
    prefix = source["repository_path"]
    paths = run(["git", "ls-tree", "-r", "--name-only", commit, "--", prefix], results)
    files = {}
    for path in paths.decode().splitlines():
        if path.endswith(".py"):
            data = run(["git", "show", f"{commit}:{path}"], results)
            files[str(Path(path).relative_to(prefix))] = hashlib.sha256(
                data
            ).hexdigest()
    require(bool(files), "no tracked Fundamental Python source files")
    require(
        len(files) == source["file_count"] and digest(files) == source["sha256"],
        "recorded source digest differs from exact Git commit",
    )
    return files


CONTAINER_SOURCE = """
import hashlib,json,platform,sys
from importlib.metadata import version
from pathlib import Path
root=Path(sys.argv[1])
files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
       for p in sorted(root.rglob('*.py'))}
print(json.dumps({'files':files,'runtime_pins':{'python':platform.python_version(),
    'arelle-release':version('arelle-release'),'pydantic':version('pydantic')}}))
"""


def check_container(
    service: dict[str, Any],
    specification: dict[str, Any],
    compose: list[str],
    results: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    name = specification["service"]
    ids = (
        run([*compose, "ps", "--format", "{{.Name}}", name], results)
        .decode()
        .splitlines()
    )
    require(len(ids) == 1, f"expected one running {name} container")
    container = json.loads(run(["docker", "inspect", ids[0]], results))[0]
    labels = container["Config"]["Labels"]
    require(
        labels.get("com.docker.compose.project") == service["compose_project"],
        f"{name} belongs to another Compose project",
    )
    require(
        labels.get("com.docker.compose.service") == name,
        f"{name} service label differs",
    )
    state = container["State"]
    require(
        state.get("Running") is True
        and state.get("Health", {}).get("Status") == "healthy",
        f"{name} is not healthy",
    )
    config_hash = run([*compose, "config", "--hash", name], results).decode().split()
    require(
        len(config_hash) == 2
        and config_hash[0] == name
        and labels.get("com.docker.compose.config-hash") == config_hash[1],
        f"{name} was started with a different Compose configuration",
    )
    bindings = run(
        [*compose, "port", name, str(specification["container_port"])], results
    )
    binding = bindings.decode().strip()
    require(
        binding
        == f"{specification['published_host']}:{specification['published_port']}",
        f"{name} published binding differs from the recorded host and port",
    )
    return ids[0], container


def verify(manifest: dict[str, Any]) -> dict[str, Any]:
    errors = validate_manifest(manifest, require_sec_identity=True)
    require(not errors, "; ".join(errors))
    require(
        manifest["schema_version"] == 2, "service preflight requires schema_version=2"
    )
    results: list[dict[str, Any]] = []
    head = check_git(manifest, results)
    service = manifest["runtime"]["fundamental"]
    env_files = [Path(entry["path"]) for entry in service["env_files"]]
    for entry, path in zip(service["env_files"], env_files, strict=True):
        require(
            hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"],
            f"recorded env file digest changed: {path}",
        )
    compose_files = [Path(path) for path in service["compose_files"]]
    errors = validate_compose_inputs(
        label="fundamental",
        env_file=None,
        env_files=env_files,
        compose_files=compose_files,
        require_paths=True,
        require_sec_user_agent=True,
    )
    require(not errors, "; ".join(errors))
    compose = ["docker", "compose"]
    for path in env_files:
        compose.extend(["--env-file", str(path)])
    compose.extend(["-p", service["compose_project"]])
    for path in compose_files:
        compose.extend(["-f", str(path)])
    run([*compose, "config", "--quiet"], results)
    if os.environ.get("START_ACCEPTANCE_STACK", "0") == "1":
        args = [*compose, "up", "-d", "--wait"]
        if os.environ.get("ACCEPTANCE_BUILD", "0") == "1":
            args.append("--build")
        run(
            [
                *args,
                service["service"],
                *[d["service"] for d in service["dependencies"]],
            ],
            results,
        )
    main_id, main = check_container(service, service, compose, results)
    containers = [main]
    for dependency in service["dependencies"]:
        _, container = check_container(service, dependency, compose, results)
        containers.append(container)
    networks = set().union(*(set(c["NetworkSettings"]["Networks"]) for c in containers))
    volumes = {
        m["Name"] for c in containers for m in c["Mounts"] if m["Type"] == "volume"
    }
    require(
        networks == set(service["networks"]),
        "running networks differ from runtime tuple",
    )
    require(
        volumes == set(service["volumes"]), "running volumes differ from runtime tuple"
    )
    for kind, names in (("network", networks), ("volume", volumes)):
        for name in sorted(names):
            resource = json.loads(run(["docker", kind, "inspect", name], results))[0]
            require(
                resource.get("Labels", {}).get("com.docker.compose.project")
                == service["compose_project"],
                f"{kind} is not owned by this Compose project: {name}",
            )
    require(
        main["Image"] == service["image_id"],
        "running Fundamental image differs from runtime tuple",
    )
    expected = source_files(manifest["commit"], service["source"], results)
    actual = json.loads(
        run(
            [
                "docker",
                "exec",
                main_id,
                "python",
                "-c",
                CONTAINER_SOURCE,
                service["source"]["container_path"],
            ],
            results,
        )
    )
    require(
        actual["files"] == expected,
        "installed Fundamental source differs from exact Git commit",
    )
    require(
        actual["runtime_pins"] == service["runtime_pins"],
        "container runtime pins differ",
    )
    url = service["url"].rstrip("/") + "/readyz"
    with urlopen(url, timeout=10) as response:
        ready = json.load(response)
    require(ready.get("status") == "ready", "Fundamental /readyz is not ready")
    require(
        ready.get("capabilities", {}).get("identity_resolution_configured") is True,
        "Fundamental SEC identity capability is not configured",
    )
    inputs = {"manifest": manifest, "head": head}
    output = {
        "status": "pass",
        "scope": "fundamental-service",
        "source_digest": digest(expected),
        "runtime_pins": actual["runtime_pins"],
        "readiness": ready,
        "commands": results,
        "full_replay_acceptance": False,
    }
    return {
        "schema_version": "acceptance.service-preflight.v1",
        "commit": manifest["commit"],
        "head": head,
        "input_digest": digest(inputs),
        "output_digest": digest(output),
        "output": output,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report-directory", type=Path)
    args = parser.parse_args()
    try:
        report = verify(load_manifest(args.manifest))
        ref = publish(args.report_directory, report) if args.report_directory else None
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"acceptance service preflight: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "pass",
                "commit": report["commit"],
                "input_digest": report["input_digest"],
                "output_digest": report["output_digest"],
                "report": ref,
                "full_replay_acceptance": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
