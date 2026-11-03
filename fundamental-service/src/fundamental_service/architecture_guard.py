"""Small dependency guard for the isolated service package."""

from __future__ import annotations

import ast
from pathlib import Path


FORBIDDEN_PREFIXES = ("src.agents", "finance_agent_core", "agents")


def check(root: Path | None = None) -> list[str]:
    package_root = root or Path(__file__).resolve().parents[1]
    failures: list[str] = []
    for path in package_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Import):
                name = node.names[0].name
            elif isinstance(node, ast.ImportFrom) and node.module:
                name = node.module
            if name and name.startswith(FORBIDDEN_PREFIXES):
                failures.append(f"{path}: forbidden import {name}")
    return failures


if __name__ == "__main__":
    errors = check()
    if errors:
        raise SystemExit("\n".join(errors))
