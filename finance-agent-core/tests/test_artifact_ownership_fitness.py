from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = BACKEND_ROOT / "src"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def _consumer(path: Path) -> str:
    parts = path.relative_to(SOURCE_ROOT).parts
    if parts[0] == "agents":
        return f"agent:{parts[1]}"
    if parts[0] == "artifacts":
        return "feature:artifacts"
    return f"feature:{parts[0]}"


def test_agents_use_only_the_public_artifact_facade() -> None:
    forbidden_prefixes = (
        "src.services.artifact_manager",
        "src.interface.artifacts",
    )
    violations: list[str] = []
    for path in (SOURCE_ROOT / "agents").rglob("*.py"):
        for module in _imports(path):
            if module.startswith(forbidden_prefixes):
                violations.append(f"{path}: {module}")
            if module.startswith("src.artifacts.") and module != "src.artifacts.public":
                violations.append(f"{path}: private artifact module {module}")

    assert not violations, "Agent artifact ownership violations:\n" + "\n".join(
        sorted(violations)
    )


def test_kernel_has_no_artifact_or_agent_contract_dependencies() -> None:
    violations = []
    for path in (SOURCE_ROOT / "shared/kernel").rglob("*.py"):
        for module in _imports(path):
            if module.startswith(("src.artifacts", "src.agents")):
                violations.append(f"{path}: {module}")

    assert not violations, (
        "Kernel dependencies must remain domain-neutral:\n"
        + "\n".join(sorted(violations))
    )


def test_artifact_application_uses_ports_without_database_dependencies() -> None:
    application_files = (
        SOURCE_ROOT / "artifacts/application/ports.py",
        SOURCE_ROOT / "artifacts/application/service.py",
        SOURCE_ROOT / "artifacts/application/typed_artifact_port.py",
    )
    violations = []
    for path in application_files:
        for module in _imports(path):
            if module.startswith(("sqlalchemy", "src.infrastructure")):
                violations.append(f"{path}: {module}")

    assert not violations, (
        "Application must depend on ports, not persistence:\n"
        + "\n".join(sorted(violations))
    )


def test_shared_artifact_contract_modules_have_multiple_feature_consumers() -> None:
    package = SOURCE_ROOT / "shared/artifacts"
    modules = {
        path.stem: path for path in package.glob("*.py") if path.name != "__init__.py"
    }
    consumers: dict[str, set[str]] = defaultdict(set)
    dependencies: dict[str, set[str]] = defaultdict(set)

    for path in SOURCE_ROOT.rglob("*.py"):
        is_shared_module = path.parent == package
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            prefix = "src.shared.artifacts."
            if node.module and node.module.startswith(prefix):
                dependency = node.module.removeprefix(prefix).split(".", 1)[0]
            elif is_shared_module and node.level == 1 and node.module:
                dependency = node.module.split(".", 1)[0]
            else:
                continue
            if dependency not in modules:
                continue
            if is_shared_module:
                dependencies[path.stem].add(dependency)
            else:
                consumers[dependency].add(_consumer(path))

    changed = True
    while changed:
        changed = False
        for module, imported_modules in dependencies.items():
            for imported_module in imported_modules:
                before = len(consumers[imported_module])
                consumers[imported_module].update(consumers[module])
                changed |= len(consumers[imported_module]) != before

    underused = {
        module: sorted(consumers[module])
        for module in modules
        if len(consumers[module]) < 2
    }
    assert (
        not underused
    ), f"Shared artifact modules need multiple consumers: {underused}"


def test_legacy_artifact_owners_are_removed() -> None:
    assert not (SOURCE_ROOT / "services/artifact_manager.py").exists()
    assert not tuple((SOURCE_ROOT / "interface/artifacts").rglob("*.py"))
    assert not tuple((SOURCE_ROOT / "shared/cross_agent/data").rglob("*.py"))
