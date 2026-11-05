"""Small dependency guard for the isolated service package."""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PREFIXES = ("src.agents", "finance_agent_core", "agents")
LEGACY_AUTH_MARKERS = (
    "FUNDAMENTAL_SERVICE_" + "AUTH_TOKEN",
    "FUNDAMENTAL_SERVICE_" + "SIGNING_KEY",
    "OperationsConfig." + "auth_token",
    "OperationsConfig." + "signing_key",
    "require" + "_auth",
)


def check(root: Path | None = None) -> list[str]:
    package_root = root or Path(__file__).resolve().parents[1]
    failures: list[str] = []
    for path in package_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Import):
                name = node.names[0].name
            elif isinstance(node, ast.ImportFrom) and node.module:
                name = node.module
            if name and name.startswith(FORBIDDEN_PREFIXES):
                failures.append(f"{path}: forbidden import {name}")
        for marker in LEGACY_AUTH_MARKERS:
            if marker in source:
                failures.append(f"{path}: legacy authentication marker {marker}")
    dockerfile = package_root / "Dockerfile"
    if dockerfile.is_file() and "internal-contracts" not in dockerfile.read_text(
        encoding="utf-8"
    ):
        failures.append(f"{dockerfile}: shared internal-contract package is not copied")
    return failures


if __name__ == "__main__":
    errors = check()
    if errors:
        raise SystemExit("\n".join(errors))
