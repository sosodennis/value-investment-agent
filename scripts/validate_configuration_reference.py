#!/usr/bin/env python3
"""Check that the configuration reference covers every repository env key."""

from __future__ import annotations

import re
import sys
from pathlib import Path

KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")
ASSIGNMENT_RE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=")
INTERPOLATION_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)")
INDEX_RE = re.compile(r"^\s*- `([A-Z][A-Z0-9_]*)`\s*$", re.MULTILINE)
START_MARKER = "<!-- begin-config-key-index -->"
END_MARKER = "<!-- end-config-key-index -->"

SOURCE_FILES = (
    Path(".env.example"),
    Path(".env.staging.example"),
    Path("docker-compose.yml"),
    Path("docker-compose.override.yml"),
    Path("docker-compose.production.yml"),
)


def configuration_keys(root: Path) -> set[str]:
    keys: set[str] = set()
    paths = [root / path for path in SOURCE_FILES]
    paths.extend(sorted((root / "compose/verification").glob("*.yml")))
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        keys.update(INTERPOLATION_RE.findall(text))
        keys.update(
            match.group(1)
            for line in text.splitlines()
            if (match := ASSIGNMENT_RE.match(line))
        )
    return {key for key in keys if KEY_RE.fullmatch(key)}


def reference_index(text: str) -> list[str]:
    try:
        start = text.index(START_MARKER) + len(START_MARKER)
        end = text.index(END_MARKER, start)
    except ValueError as error:
        raise ValueError(
            "configuration reference is missing the key index markers"
        ) from error
    return INDEX_RE.findall(text[start:end])


def validate(root: Path, reference_path: Path) -> list[str]:
    expected = configuration_keys(root)
    try:
        actual_list = reference_index(reference_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [str(error)]

    actual = set(actual_list)
    errors: list[str] = []
    if len(actual_list) != len(actual):
        errors.append("configuration reference key index contains duplicate keys")
    missing = sorted(expected - actual)
    if missing:
        errors.append(f"configuration reference is missing keys: {', '.join(missing)}")
    extra = sorted(actual - expected)
    if extra:
        errors.append(f"configuration reference lists unknown keys: {', '.join(extra)}")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    reference_path = root / "docs/configuration/environment-reference.md"
    errors = validate(root, reference_path)
    if errors:
        for error in errors:
            print(f"configuration reference: FAIL: {error}", file=sys.stderr)
        return 1
    print("configuration reference: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
