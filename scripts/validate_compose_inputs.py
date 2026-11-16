#!/usr/bin/env python3
"""Validate the environment inputs required by one or more Compose files."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

INTERPOLATION_RE = re.compile(
    r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:(?P<operator>:-|\-\?|:\?|\?)(?P<argument>[^}]*))?\}"
)
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PLACEHOLDER_USER_AGENTS = {
    "contact@example.com",
    "Value Investment Agent contact@example.com",
    "ValueInvestmentAgent/1.0 (contact@example.com)",
}


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not KEY_RE.fullmatch(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _compose_variables(paths: list[Path]) -> tuple[set[str], set[str]]:
    referenced: set[str] = set()
    required: set[str] = set()
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for match in INTERPOLATION_RE.finditer(text):
            name = match.group("name")
            referenced.add(name)
            if match.group("operator") in {":?", "?"}:
                required.add(name)
    return referenced, required


def _effective_value(name: str, file_values: dict[str, str]) -> str | None:
    if name in os.environ:
        return os.environ[name]
    return file_values.get(name)


def validate(
    *,
    label: str,
    env_file: Path | None,
    compose_files: list[Path],
    require_paths: bool,
    require_sec_user_agent: bool,
    env_files: list[Path] | None = None,
) -> list[str]:
    errors: list[str] = []
    paths = env_files if env_files is not None else ([env_file] if env_file else [])
    for path in paths:
        if not path.is_file():
            return [f"{label}: env file does not exist: {path}"]

    file_values: dict[str, str] = {}
    for path in paths:
        file_values.update(_read_env_file(path))
    referenced, required = _compose_variables(compose_files)

    for name in sorted(referenced & file_values.keys() & os.environ.keys()):
        if os.environ[name] != file_values[name]:
            errors.append(
                f"{label}: shell environment overrides {name}; unset the shell value "
                "or update the recorded env file"
            )
    if paths:
        shell_only = (referenced & os.environ.keys()) - file_values.keys()
        for name in sorted(shell_only):
            errors.append(
                f"{label}: shell-only Compose variable {name}; add it to the recorded env file"
            )

    missing = sorted(
        name
        for name in required
        if not (_effective_value(name, file_values) or "").strip()
    )
    for name in missing:
        errors.append(f"{label}: missing required Compose variable {name}")

    if require_paths:
        for name in sorted(required):
            value = _effective_value(name, file_values)
            if not value:
                continue
            candidate = Path(value).expanduser()
            if name.endswith("_HOST_DIR") and not candidate.is_dir():
                errors.append(
                    f"{label}: {name} must name an existing directory: {candidate}"
                )
            elif name.endswith("_HOST_PATH") and not candidate.is_file():
                errors.append(
                    f"{label}: {name} must name an existing file: {candidate}"
                )

    if require_sec_user_agent:
        user_agent = (
            _effective_value("FUNDAMENTAL_SEC_USER_AGENT", file_values) or ""
        ).strip()
        if (
            not user_agent
            or user_agent in PLACEHOLDER_USER_AGENTS
            or "contact@example.com" in user_agent
        ):
            errors.append(
                f"{label}: FUNDAMENTAL_SEC_USER_AGENT must be a non-placeholder contact string"
            )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--compose-file", type=Path, action="append", required=True)
    parser.add_argument("--require-paths", action="store_true")
    parser.add_argument("--require-sec-user-agent", action="store_true")
    args = parser.parse_args(argv)

    missing_files = [path for path in args.compose_file if not path.is_file()]
    if missing_files:
        errors = [
            f"{args.label}: Compose file does not exist: {path}"
            for path in missing_files
        ]
    else:
        errors = validate(
            label=args.label,
            env_file=args.env_file,
            compose_files=args.compose_file,
            require_paths=args.require_paths,
            require_sec_user_agent=args.require_sec_user_agent,
        )

    if errors:
        for error in errors:
            print(f"compose inputs: FAIL: {error}", file=sys.stderr)
        return 1
    print(f"compose inputs: PASS label={args.label} files={len(args.compose_file)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
