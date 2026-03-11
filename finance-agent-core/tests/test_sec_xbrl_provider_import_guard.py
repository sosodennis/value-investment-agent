from __future__ import annotations

import ast
from pathlib import Path


def test_non_sec_xbrl_modules_use_provider_entrypoint() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scan_roots = [
        repo_root / "finance-agent-core" / "src",
        repo_root / "finance-agent-core" / "scripts",
    ]
    banned_imports = (
        "src.agents.fundamental.forward_signals.infrastructure.sec_xbrl.forward_signals_text",
        "src.agents.fundamental.forward_signals.infrastructure.sec_xbrl.forward_signals",
        "src.agents.fundamental.financial_statements.infrastructure.sec_xbrl.extract.financial_payload_service",
    )

    violations: list[str] = []
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            relative_path = path.relative_to(repo_root)
            # Internal implementation modules in sec_xbrl can reference each other.
            if any(
                segment in str(relative_path)
                for segment in (
                    "src/agents/fundamental/forward_signals/infrastructure/sec_xbrl/",
                    "src/agents/fundamental/financial_statements/infrastructure/sec_xbrl/",
                )
            ):
                continue
            content = path.read_text(encoding="utf-8")
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module_name = node.module
                    if module_name in banned_imports:
                        violations.append(f"{relative_path}: {module_name}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in banned_imports:
                            violations.append(f"{relative_path}: {alias.name}")

    assert not violations, (
        "Direct sec_xbrl implementation imports found outside sec_xbrl package:\n"
        + "\n".join(sorted(violations))
    )
