#!/usr/bin/env python3
"""Inspect and optionally remove only a retired Compose project's HF caches."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

CACHE_VOLUMES = (
    "hf_cache",
    "inference_news_hf_cache",
    "inference_fls_hf_cache",
)
INSPECTOR_IMAGE = "alpine:3.20"
PROJECT_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}\Z")


def docker_output(*arguments: str) -> str:
    result = subprocess.run(
        ["docker", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"docker {' '.join(arguments[:3])} failed: {detail}")
    return result.stdout.strip()


def inspect_contents(volume_name: str) -> str:
    docker_output("image", "inspect", INSPECTOR_IMAGE)
    return docker_output(
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--mount",
        f"type=volume,source={volume_name},target=/cache,readonly",
        "--entrypoint",
        "sh",
        INSPECTOR_IMAGE,
        "-c",
        "du -sh /cache && find /cache -mindepth 1 -maxdepth 2 -print | sort | head -40",
    )


def plan_volumes(project: str) -> list[tuple[str, str, list[str]]]:
    project_volumes = set(
        docker_output(
            "volume",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            "{{.Name}}",
        ).splitlines()
    )
    plan: list[tuple[str, str, list[str]]] = []
    for logical_name in CACHE_VOLUMES:
        volume_name = f"{project}_{logical_name}"
        if volume_name not in project_volumes:
            continue

        inspected = json.loads(docker_output("volume", "inspect", volume_name))[0]
        labels = inspected.get("Labels") or {}
        if labels.get("com.docker.compose.project") != project:
            raise RuntimeError(f"{volume_name} has a different Compose project label")
        if labels.get("com.docker.compose.volume") != logical_name:
            raise RuntimeError(f"{volume_name} has an unexpected Compose volume label")
        if inspected.get("Driver") != "local":
            raise RuntimeError(f"{volume_name} is not a local Compose volume")

        attached = docker_output(
            "ps", "--all", "--quiet", "--filter", f"volume={volume_name}"
        ).splitlines()
        contents = inspect_contents(volume_name)
        plan.append((volume_name, contents, attached))
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project", required=True, help="Exact Docker Compose project name"
    )
    parser.add_argument(
        "--confirm-retired",
        action="store_true",
        help="Remove the inspected cache volumes after verifying the project is retired",
    )
    arguments = parser.parse_args()
    if not PROJECT_PATTERN.fullmatch(arguments.project):
        parser.error(
            "project must be a lowercase Compose name of at most 63 characters"
        )

    try:
        plan = plan_volumes(arguments.project)
        if not plan:
            print(f"No allowlisted HF cache volumes exist for {arguments.project}.")
            return 0

        for volume_name, contents, attached in plan:
            print(f"{volume_name}: attached containers={len(attached)}")
            for line in contents.splitlines():
                print(f"  {line}")

        if not arguments.confirm_retired:
            print("Dry run only; no volumes were removed.")
            print("Pass --confirm-retired only after retiring this Compose project.")
            return 0

        project_containers = docker_output(
            "ps",
            "--all",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={arguments.project}",
        ).splitlines()
        if project_containers:
            raise RuntimeError(
                f"project still has {len(project_containers)} container(s); "
                "run docker compose down without --volumes first"
            )
        attached_volumes = [name for name, _, attached in plan if attached]
        if attached_volumes:
            raise RuntimeError(
                "cache volumes are still mounted: " + ", ".join(attached_volumes)
            )

        for volume_name, _, _ in plan:
            print(f"Removing {volume_name}")
            docker_output("volume", "rm", volume_name)
    except (RuntimeError, json.JSONDecodeError, IndexError) as error:
        print(f"Refusing cleanup: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
