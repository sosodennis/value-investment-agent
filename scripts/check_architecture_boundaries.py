#!/usr/bin/env python3
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "finance-agent-core" / "src"
BASELINE_FILE = REPO_ROOT / "scripts" / "architecture-boundary-baseline.txt"

AGENT_NAMES = {
    "fundamental_analysis",
    "financial_news_research",
    "technical_analysis",
    "debate",
    "intent_extraction",
}


@dataclass(frozen=True)
class Violation:
    code: str
    file: str
    line: int
    imported: str
    message: str

    def key(self) -> str:
        return f"{self.code}|{self.file}:{self.line}|{self.imported}"


def iter_python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def module_name_from_path(path: Path) -> str:
    rel = path.relative_to(SRC_ROOT)
    return "src." + ".".join(rel.with_suffix("").parts)


def resolve_import(module_name: str, node: ast.ImportFrom) -> str | None:
    current_pkg = module_name.rsplit(".", 1)[0]
    if node.level == 0:
        return node.module

    pkg_parts = current_pkg.split(".")
    pop_count = node.level - 1
    if pop_count > len(pkg_parts):
        return None
    base = pkg_parts[: len(pkg_parts) - pop_count]
    if node.module:
        return ".".join(base + [node.module])
    return ".".join(base)


def extract_imports(path: Path) -> list[tuple[int, str]]:
    module_name = module_name_from_path(path)
    tree = ast.parse(path.read_text(), filename=str(path))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            resolved = resolve_import(module_name, node)
            if resolved:
                out.append((node.lineno, resolved))
    return out


def parse_agent_owner(module_name: str) -> str | None:
    parts = module_name.split(".")
    # src.workflow.nodes.<agent>....
    if len(parts) >= 5 and parts[0:3] == ["src", "workflow", "nodes"]:
        candidate = parts[3]
        if candidate in AGENT_NAMES:
            return candidate
    return None


def is_tools_module(module_name: str) -> bool:
    parts = module_name.split(".")
    return (
        len(parts) >= 6
        and parts[0:3] == ["src", "workflow", "nodes"]
        and "tools" in parts[4:]
    )


def collect_violations() -> list[Violation]:
    violations: list[Violation] = []

    for file_path in iter_python_files(SRC_ROOT):
        module_name = module_name_from_path(file_path)
        owner = parse_agent_owner(module_name)

        for lineno, imported in extract_imports(file_path):
            # Rule XAG001: cross-agent internal import in workflow nodes
            if owner and imported.startswith("src.workflow.nodes."):
                imported_parts = imported.split(".")
                if len(imported_parts) >= 4:
                    imported_owner = imported_parts[3]
                    if imported_owner in AGENT_NAMES and imported_owner != owner:
                        violations.append(
                            Violation(
                                code="XAG001",
                                file=str(file_path.relative_to(REPO_ROOT)),
                                line=lineno,
                                imported=imported,
                                message="cross-agent internal import is forbidden",
                            )
                        )

            # Rule XLY001: tools modules cannot import services implementations
            if is_tools_module(module_name) and imported.startswith("src.services"):
                violations.append(
                    Violation(
                        code="XLY001",
                        file=str(file_path.relative_to(REPO_ROOT)),
                        line=lineno,
                        imported=imported,
                        message="tools module importing services layer is forbidden",
                    )
                )

    # de-duplicate
    dedup = {v.key(): v for v in violations}
    return sorted(dedup.values(), key=lambda v: (v.code, v.file, v.line, v.imported))


def read_baseline() -> set[str]:
    if not BASELINE_FILE.exists():
        return set()
    keys: set[str] = set()
    for line in BASELINE_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        keys.add(line)
    return keys


def print_current(violations: list[Violation]) -> None:
    for v in violations:
        print(v.key())


def main() -> int:
    mode = "check"
    if len(sys.argv) > 1 and sys.argv[1] in {"--print-current"}:
        mode = "print"

    violations = collect_violations()
    if mode == "print":
        print_current(violations)
        return 0

    baseline = read_baseline()
    current = {v.key() for v in violations}
    new_violations = sorted(current - baseline)
    resolved = sorted(baseline - current)

    if resolved:
        print("Resolved baseline violations (consider updating baseline):")
        for item in resolved:
            print(f"  - {item}")

    if new_violations:
        print("New architecture boundary violations detected:")
        for item in new_violations:
            print(f"  - {item}")
        print(
            "\nIf intentional, update scripts/architecture-boundary-baseline.txt in the same PR."
        )
        return 1

    print("Architecture boundary check passed (no new violations).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
