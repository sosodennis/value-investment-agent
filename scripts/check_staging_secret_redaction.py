#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def read_secrets(env_file: Path) -> dict[str, str]:
    secrets: dict[str, str] = {}
    for raw_line in env_file.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value and name.endswith(("_EMAIL", "_KEY", "_PASSWORD", "_TOKEN")):
            secrets[name] = value
    if not secrets:
        raise ValueError("environment file contains no non-empty secret values")
    return secrets


def read_secret_values(secret_file: Path, start: int) -> dict[str, str]:
    values: dict[str, str] = {}
    if secret_file.suffix.lower() == ".csv":
        with secret_file.open(newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                value = (row.get("api_key") or "").strip()
                if value:
                    values[f"imported_key_{start + row_number - 2}"] = value
        return values
    for row_number, raw_line in enumerate(
        secret_file.read_text(errors="replace").splitlines(), 1
    ):
        value = raw_line.strip()
        if value:
            values[f"secret_file_{start + row_number - 1}"] = value
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--secret-value-file", type=Path, action="append", default=[])
    parser.add_argument("--file", type=Path, action="append", default=[])
    parser.add_argument("--stdin", action="store_true")
    args = parser.parse_args()
    if not args.file and not args.stdin:
        parser.error("provide at least one --file or --stdin")

    try:
        secrets = read_secrets(args.env_file)
        next_secret_index = len(secrets) + 1
        for secret_file in args.secret_value_file:
            secrets.update(read_secret_values(secret_file, next_secret_index))
            next_secret_index = len(secrets) + 1
        tracked_example = args.env_file.parent / ".env.staging.example"
        if tracked_example.exists():
            example_secrets = read_secrets(tracked_example)
            if any(
                value == secrets.get(name) for name, value in example_secrets.items()
            ):
                print(
                    "tracked staging example contains a staging secret", file=sys.stderr
                )
                return 1
        matches: list[tuple[str, str]] = []
        for path in args.file:
            for line_number, line in enumerate(
                path.read_text(errors="replace").splitlines(), 1
            ):
                matches.extend(
                    (name, f"{path}:{line_number}")
                    for name, value in secrets.items()
                    if value in line
                )
        if args.stdin:
            for line_number, line in enumerate(sys.stdin, 1):
                matches.extend(
                    (name, f"stdin:{line_number}")
                    for name, value in secrets.items()
                    if value in line
                )
    except (OSError, ValueError) as error:
        print(f"staging secret scan could not run: {error}", file=sys.stderr)
        return 2

    if matches:
        for name, location in matches:
            print(f"secret from {name} found in {location}", file=sys.stderr)
        return 1
    print(f"staging secret scan passed ({len(args.file) + int(args.stdin)} artifacts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
