from __future__ import annotations

import ast
from pathlib import Path


def _is_banned_import(module_name: str, banned_prefix: str) -> bool:
    return module_name == banned_prefix or module_name.startswith(f"{banned_prefix}.")


def test_no_legacy_fundamental_data_imports() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scan_roots = [
        repo_root / "finance-agent-core" / "src",
        repo_root / "finance-agent-core" / "tests",
        repo_root / "finance-agent-core" / "scripts",
    ]
    banned_prefix = "src.agents.fundamental.data"

    violations: list[str] = []
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path.name == "test_fundamental_import_hygiene_guard.py":
                continue
            content = path.read_text(encoding="utf-8")
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module_name = node.module
                    if module_name and _is_banned_import(module_name, banned_prefix):
                        relative_path = path.relative_to(repo_root)
                        violations.append(
                            f"{relative_path}:{node.lineno}: {module_name}"
                        )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if _is_banned_import(alias.name, banned_prefix):
                            relative_path = path.relative_to(repo_root)
                            violations.append(
                                f"{relative_path}:{node.lineno}: {alias.name}"
                            )

    assert not violations, "Legacy fundamental.data imports found:\n" + "\n".join(
        sorted(violations)
    )


def test_domain_report_semantics_has_no_source_label_normalizer() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    target = (
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "fundamental"
        / "subdomains"
        / "financial_statements"
        / "domain"
        / "report_semantics.py"
    )
    tree = ast.parse(target.read_text(encoding="utf-8"))
    banned_functions = {
        "normalize_extension_type_token",
        "infer_extension_type_from_extension",
    }
    present = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in banned_functions
    }
    assert not present, (
        "report_semantics.py should not host source-label normalization helpers: "
        + ", ".join(sorted(present))
    )


def test_no_legacy_generic_fundamental_imports() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scan_roots = [
        repo_root / "finance-agent-core" / "src",
        repo_root / "finance-agent-core" / "tests",
        repo_root / "finance-agent-core" / "scripts",
    ]
    banned_prefixes = [
        "src.agents.fundamental.domain.models",
        "src.agents.fundamental.domain.rules",
        "src.agents.fundamental.domain.services",
        "src.agents.fundamental.subdomains.financial_statements.infrastructure.sec_xbrl.models",
        "src.agents.fundamental.subdomains.core_valuation.domain.backtest_contracts",
        "src.agents.fundamental.subdomains.core_valuation.domain.backtest_io_service",
        "src.agents.fundamental.subdomains.core_valuation.domain.backtest_runtime_service",
        "src.agents.fundamental.subdomains.core_valuation.domain.backtest_drift_service",
        "src.agents.fundamental.subdomains.core_valuation.domain.backtest_report_service",
    ]

    violations: list[str] = []
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path.name == "test_fundamental_import_hygiene_guard.py":
                continue
            content = path.read_text(encoding="utf-8")
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module_name = node.module
                    if module_name and any(
                        _is_banned_import(module_name, prefix)
                        for prefix in banned_prefixes
                    ):
                        relative_path = path.relative_to(repo_root)
                        violations.append(
                            f"{relative_path}:{node.lineno}: {module_name}"
                        )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(
                            _is_banned_import(alias.name, prefix)
                            for prefix in banned_prefixes
                        ):
                            relative_path = path.relative_to(repo_root)
                            violations.append(
                                f"{relative_path}:{node.lineno}: {alias.name}"
                            )

    assert not violations, "Legacy generic fundamental imports found:\n" + "\n".join(
        sorted(violations)
    )


def test_no_legacy_generic_fundamental_module_files() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    banned_paths = [
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "fundamental"
        / "domain"
        / "models.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "fundamental"
        / "domain"
        / "rules.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "fundamental"
        / "domain"
        / "services.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "fundamental"
        / "infrastructure"
        / "sec_xbrl"
        / "models.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "fundamental"
        / "domain"
        / "valuation"
        / "backtest_contracts.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "fundamental"
        / "domain"
        / "valuation"
        / "backtest_io_service.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "fundamental"
        / "domain"
        / "valuation"
        / "backtest_runtime_service.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "fundamental"
        / "domain"
        / "valuation"
        / "backtest_drift_service.py",
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "fundamental"
        / "domain"
        / "valuation"
        / "backtest_report_service.py",
    ]

    existing = [path for path in banned_paths if path.exists()]
    assert not existing, "Legacy generic module files should be removed:\n" + "\n".join(
        sorted(str(path.relative_to(repo_root)) for path in existing)
    )
