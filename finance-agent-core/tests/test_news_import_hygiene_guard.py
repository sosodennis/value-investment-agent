from __future__ import annotations

import ast
from pathlib import Path


def _is_banned_import(module_name: str, banned_prefix: str) -> bool:
    return module_name == banned_prefix or module_name.startswith(f"{banned_prefix}.")


def _annotation_contains_object(annotation: ast.expr | None) -> bool:
    if annotation is None:
        return False
    return any(
        isinstance(node, ast.Name) and node.id == "object"
        for node in ast.walk(annotation)
    )


def test_no_legacy_news_data_imports() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scan_roots = [
        repo_root / "finance-agent-core" / "src",
        repo_root / "finance-agent-core" / "tests",
        repo_root / "finance-agent-core" / "scripts",
    ]
    banned_prefix = "src.agents.news.data"

    violations: list[str] = []
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path.name == "test_news_import_hygiene_guard.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module_name = node.module
                    if module_name and _is_banned_import(module_name, banned_prefix):
                        violations.append(
                            f"{path.relative_to(repo_root)}:{node.lineno}: {module_name}"
                        )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if _is_banned_import(alias.name, banned_prefix):
                            violations.append(
                                f"{path.relative_to(repo_root)}:{node.lineno}: {alias.name}"
                            )

    assert not violations, "Legacy news.data imports found:\n" + "\n".join(
        sorted(violations)
    )


def test_no_legacy_generic_news_imports() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scan_roots = [
        repo_root / "finance-agent-core" / "src",
        repo_root / "finance-agent-core" / "tests",
        repo_root / "finance-agent-core" / "scripts",
    ]
    banned_prefixes = [
        "src.agents.news.domain.models",
        "src.agents.news.domain.services",
        "src.agents.news.domain.policies",
        "src.agents.news.domain.prompt_builder",
        "src.agents.news.application.view_models",
    ]

    violations: list[str] = []
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path.name == "test_news_import_hygiene_guard.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module_name = node.module
                    if module_name and any(
                        _is_banned_import(module_name, prefix)
                        for prefix in banned_prefixes
                    ):
                        violations.append(
                            f"{path.relative_to(repo_root)}:{node.lineno}: {module_name}"
                        )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(
                            _is_banned_import(alias.name, prefix)
                            for prefix in banned_prefixes
                        ):
                            violations.append(
                                f"{path.relative_to(repo_root)}:{node.lineno}: {alias.name}"
                            )

    assert not violations, "Legacy generic news imports found:\n" + "\n".join(
        sorted(violations)
    )


def test_no_legacy_generic_news_module_files() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    banned_paths = [
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "news"
        / "application"
        / "view_models.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "news"
        / "domain"
        / "models.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "news"
        / "domain"
        / "services.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "news"
        / "domain"
        / "policies.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "news"
        / "domain"
        / "prompt_builder.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "news"
        / "data"
        / "__init__.py",
    ]

    existing = [path for path in banned_paths if path.exists()]
    assert not existing, "Legacy news modules should be removed:\n" + "\n".join(
        sorted(str(path.relative_to(repo_root)) for path in existing)
    )


def test_news_artifact_repository_port_has_no_object_typed_boundaries() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    target = (
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "news"
        / "application"
        / "ports.py"
    )
    tree = ast.parse(target.read_text(encoding="utf-8"))
    artifact_repo_class = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "INewsArtifactRepository":
            artifact_repo_class = node
            break

    assert artifact_repo_class is not None, "INewsArtifactRepository not found"

    violations: list[str] = []
    for node in artifact_repo_class.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if _annotation_contains_object(node.returns):
            violations.append(f"{node.name}: return annotation contains object")

        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            if arg.arg in {"self", "cls"}:
                continue
            if _annotation_contains_object(arg.annotation):
                violations.append(
                    f"{node.name}: parameter '{arg.arg}' annotation contains object"
                )

    assert not violations, (
        "INewsArtifactRepository should not use object-typed boundaries:\n"
        + "\n".join(sorted(violations))
    )
