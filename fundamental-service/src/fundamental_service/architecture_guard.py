"""Small dependency guard for the isolated service package."""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PREFIXES = ("src.agents", "finance_agent_core", "agents")
SOURCE_PLAN_MODULES = frozenset(
    {"source_plan_contracts.py", "current_preparation.py", "original_source_plan.py"}
)
LEGACY_AUTH_MARKERS = (
    "FUNDAMENTAL_SERVICE_" + "AUTH_TOKEN",
    "FUNDAMENTAL_SERVICE_" + "SIGNING_KEY",
    "OperationsConfig." + "auth_token",
    "OperationsConfig." + "signing_key",
    "require" + "_auth",
)


def check(root: Path | None = None) -> list[str]:
    package_root = root or Path(__file__).resolve().parents[2]
    failures: list[str] = []
    paths = sorted(
        path
        for directory in ("src", "tests", "scripts")
        for path in (package_root / directory).rglob("*.py")
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
                composition_names = names
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = (node.module,)
                composition_names = (
                    node.module,
                    *(f"{node.module}.{alias.name}" for alias in node.names),
                )
            elif isinstance(node, ast.ImportFrom):
                names = tuple(alias.name for alias in node.names)
                composition_names = names
            else:
                continue
            for name in names:
                if name.startswith(FORBIDDEN_PREFIXES):
                    failures.append(f"{path}: forbidden import {name}")
            for name in composition_names:
                if (
                    path.name in SOURCE_PLAN_MODULES
                    and name.rsplit(".", 1)[-1] == "preparation_runner"
                ):
                    failures.append(
                        f"{path}: source-plan policy imports runtime composition {name}"
                    )
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
