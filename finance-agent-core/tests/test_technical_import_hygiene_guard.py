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


def test_no_legacy_technical_data_imports() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scan_roots = [
        repo_root / "finance-agent-core" / "src",
        repo_root / "finance-agent-core" / "tests",
        repo_root / "finance-agent-core" / "scripts",
    ]
    banned_prefix = "src.agents.technical.data"

    violations: list[str] = []
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path.name == "test_technical_import_hygiene_guard.py":
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

    assert not violations, "Legacy technical.data imports found:\n" + "\n".join(
        sorted(violations)
    )


def test_no_legacy_generic_technical_imports() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scan_roots = [
        repo_root / "finance-agent-core" / "src",
        repo_root / "finance-agent-core" / "tests",
        repo_root / "finance-agent-core" / "scripts",
    ]
    banned_prefixes = [
        "src.agents.technical.domain.models",
        "src.agents.technical.domain.services",
        "src.agents.technical.domain.policies",
        "src.agents.technical.domain.prompt_builder",
        "src.agents.technical.domain.backtest",
        "src.agents.technical.domain.fracdiff",
        "src.agents.technical.domain.signal_policy",
        "src.agents.technical.application.semantic_service",
        "src.agents.technical.application.semantic_context_formatter_service",
        "src.agents.technical.infrastructure",
        "src.agents.technical.infrastructure.market_data",
    ]

    violations: list[str] = []
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path.name == "test_technical_import_hygiene_guard.py":
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

    assert not violations, "Legacy generic technical imports found:\n" + "\n".join(
        sorted(violations)
    )


def test_no_legacy_generic_technical_module_files() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    banned_paths = [
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "application"
        / "semantic_service.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "application"
        / "semantic_context_formatter_service.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "domain"
        / "models.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "domain"
        / "services.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "domain"
        / "policies.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "domain"
        / "prompt_builder.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "data"
        / "__init__.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "infrastructure"
        / "__init__.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "infrastructure"
        / "artifacts"
        / "technical_artifact_repository.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "infrastructure"
        / "llm"
        / "technical_interpretation_provider.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "infrastructure"
        / "market_data"
        / "yahoo_market_data_provider.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "infrastructure"
        / "market_data"
        / "yahoo_ohlcv_provider.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "infrastructure"
        / "market_data"
        / "yahoo_risk_free_rate_provider.py",
    ]

    existing = [path for path in banned_paths if path.exists()]
    assert not existing, "Legacy technical modules should be removed:\n" + "\n".join(
        sorted(str(path.relative_to(repo_root)) for path in existing)
    )


def test_backtest_runtime_port_has_no_object_typed_boundaries() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    target = (
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "application"
        / "ports.py"
    )
    tree = ast.parse(target.read_text(encoding="utf-8"))
    backtest_runtime_class = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ITechnicalBacktestRuntime":
            backtest_runtime_class = node
            break

    assert backtest_runtime_class is not None, "ITechnicalBacktestRuntime not found"

    violations: list[str] = []
    for node in backtest_runtime_class.body:
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
        "ITechnicalBacktestRuntime should not use object-typed boundaries:\n"
        + "\n".join(sorted(violations))
    )


def test_artifact_repository_port_has_no_object_typed_boundaries() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    target = (
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "application"
        / "ports.py"
    )
    tree = ast.parse(target.read_text(encoding="utf-8"))
    artifact_repo_class = None
    for node in tree.body:
        if (
            isinstance(node, ast.ClassDef)
            and node.name == "ITechnicalArtifactRepository"
        ):
            artifact_repo_class = node
            break

    assert artifact_repo_class is not None, "ITechnicalArtifactRepository not found"

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
        "ITechnicalArtifactRepository should not use object-typed boundaries:\n"
        + "\n".join(sorted(violations))
    )


def test_decision_observability_port_has_no_object_typed_boundaries() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    target = (
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "application"
        / "ports.py"
    )
    tree = ast.parse(target.read_text(encoding="utf-8"))
    observability_port_class = None
    for node in tree.body:
        if (
            isinstance(node, ast.ClassDef)
            and node.name == "ITechnicalDecisionObservabilityPort"
        ):
            observability_port_class = node
            break

    assert (
        observability_port_class is not None
    ), "ITechnicalDecisionObservabilityPort not found"

    violations: list[str] = []
    for node in observability_port_class.body:
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
        "ITechnicalDecisionObservabilityPort should not use object-typed boundaries:\n"
        + "\n".join(sorted(violations))
    )


def test_fracdiff_runtime_service_has_no_object_typed_callables() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    target = (
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "technical"
        / "application"
        / "fracdiff_runtime_service.py"
    )
    tree = ast.parse(target.read_text(encoding="utf-8"))

    service_class = None
    for node in tree.body:
        if (
            isinstance(node, ast.ClassDef)
            and node.name == "TechnicalFracdiffRuntimeService"
        ):
            service_class = node
            break

    assert service_class is not None, "TechnicalFracdiffRuntimeService not found"

    violations: list[str] = []
    for node in service_class.body:
        if isinstance(node, ast.AnnAssign) and _annotation_contains_object(
            node.annotation
        ):
            target_name = (
                node.target.id if isinstance(node.target, ast.Name) else "<unknown>"
            )
            violations.append(f"{target_name}: annotation contains object")

    assert not violations, (
        "TechnicalFracdiffRuntimeService should not use object-typed callables:\n"
        + "\n".join(sorted(violations))
    )
