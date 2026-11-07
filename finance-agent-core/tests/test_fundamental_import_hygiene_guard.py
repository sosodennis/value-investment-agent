from __future__ import annotations

import ast
import json
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


def test_rehomed_fundamental_capabilities_have_no_legacy_imports() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scan_roots = [
        repo_root / "finance-agent-core" / "src",
        repo_root / "finance-agent-core" / "tests",
        repo_root / "finance-agent-core" / "scripts",
    ]
    moved_capabilities = (
        "core_valuation",
        "financial_statements",
        "forward_signals",
        "market_data",
        "model_selection",
    )
    violations: list[str] = []
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path.name == "test_fundamental_import_hygiene_guard.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                imported_modules: list[str] = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.append(node.module)
                elif isinstance(node, ast.Import):
                    imported_modules.extend(alias.name for alias in node.names)
                for module_name in imported_modules:
                    if any(
                        _is_banned_import(
                            module_name,
                            f"src.agents.fundamental.subdomains.{capability}",
                        )
                        for capability in moved_capabilities
                    ):
                        violations.append(
                            f"{path.relative_to(repo_root)}:{node.lineno}: {module_name}"
                        )

    assert not violations, "Legacy moved-capability imports found:\n" + "\n".join(
        sorted(violations)
    )

    for capability in moved_capabilities:
        assert (
            repo_root
            / "finance-agent-core"
            / "src"
            / "agents"
            / "fundamental"
            / "capabilities"
            / capability
            / "public.py"
        ).is_file()

    legacy_root = (
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "fundamental"
        / "subdomains"
    )
    legacy_files = [path for path in legacy_root.rglob("*") if path.is_file()]
    assert not legacy_files, "Fundamental subdomains must not contain files"


def test_domain_report_semantics_has_no_source_label_normalizer() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    target = (
        repo_root
        / "finance-agent-core"
        / "src"
        / "agents"
        / "fundamental"
        / "capabilities"
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
        "src.agents.fundamental.capabilities.financial_statements.infrastructure.sec_xbrl.models",
        "src.agents.fundamental.capabilities.core_valuation.domain.backtest_contracts",
        "src.agents.fundamental.capabilities.core_valuation.domain.backtest_io_service",
        "src.agents.fundamental.capabilities.core_valuation.domain.backtest_runtime_service",
        "src.agents.fundamental.capabilities.core_valuation.domain.backtest_drift_service",
        "src.agents.fundamental.capabilities.core_valuation.domain.backtest_report_service",
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


def test_no_active_fundamental_sec_or_report_fallback_imports() -> None:
    """Production caller layers must not reintroduce the retired fallback seams."""

    repo_root = Path(__file__).resolve().parents[2]
    source_root = repo_root / "finance-agent-core" / "src" / "agents" / "fundamental"
    scan_roots = (
        source_root / "application",
        source_root / "workflow",
        source_root / "interface",
    )
    banned_prefixes = (
        "src.agents.fundamental.capabilities.financial_statements.infrastructure.sec_xbrl",
        "src.agents.fundamental.capabilities.forward_signals.infrastructure.sec_xbrl",
        "src.agents.fundamental.application.workflow_orchestrator.valuation_flow",
        "src.agents.fundamental.application.workflow_orchestrator.services.model_selection_artifact_service",
        "src.agents.fundamental.application.workflow_orchestrator.services.valuation_",
    )

    violations: list[str] = []
    for root in scan_roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                imported_modules: list[str] = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.append(node.module)
                elif isinstance(node, ast.Import):
                    imported_modules.extend(alias.name for alias in node.names)
                for module_name in imported_modules:
                    if any(
                        _is_banned_import(module_name, prefix)
                        for prefix in banned_prefixes
                    ):
                        violations.append(
                            f"{path.relative_to(repo_root)}:{node.lineno}: {module_name}"
                        )

    assert not violations, "Active Fundamental fallback imports found:\n" + "\n".join(
        sorted(violations)
    )


def test_replay_gate_has_no_agent_sec_fallback_imports_or_flags() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    runner = (
        repo_root
        / "finance-agent-core"
        / "scripts"
        / "run_fundamental_live_replay_cohort_gate.py"
    )
    source = runner.read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned_prefixes = (
        "src.agents.fundamental.capabilities.financial_statements.infrastructure.sec_xbrl",
        "src.agents.fundamental.capabilities.forward_signals.infrastructure.sec_xbrl",
        "src.agents.fundamental.financial_statements.infrastructure.sec_xbrl",
    )
    violations: list[str] = []
    for node in ast.walk(tree):
        imported_modules: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
        elif isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        for module_name in imported_modules:
            if any(
                _is_banned_import(module_name, prefix) for prefix in banned_prefixes
            ):
                violations.append(
                    f"{runner.relative_to(repo_root)}:{node.lineno}: {module_name}"
                )

    assert not violations, "Replay gate imports Agent-owned SEC code:\n" + "\n".join(
        sorted(violations)
    )
    for retired_flag in (
        "FUNDAMENTAL_LIVE_REPLAY_ENABLE_PREWARM",
        "FUNDAMENTAL_LIVE_REPLAY_PREWARM_DEFAULT_YEARS",
        "enable_prewarm",
        "prewarm_default_years",
    ):
        assert retired_flag not in source


def test_legacy_sec_script_imports_are_explicitly_quarantined() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scan_roots = (
        repo_root / "finance-agent-core" / "scripts",
        repo_root / "scripts" / "benchmarks",
    )
    allowed_paths = {
        "finance-agent-core/scripts/benchmark_fls_backends.py",
        "finance-agent-core/scripts/benchmark_sec_forward_signals.py",
        "scripts/benchmarks/fls_workload.py",
        "scripts/benchmarks/model_inventory.py",
    }
    legacy_markers = (
        "sec_xbrl",
        "fundamental.financial_statements.infrastructure",
    )
    violations: list[str] = []
    for root in scan_roots:
        for path in root.rglob("*.py"):
            relative = path.relative_to(repo_root).as_posix()
            source = path.read_text(encoding="utf-8")
            if not any(marker in source for marker in legacy_markers):
                continue
            if relative not in allowed_paths:
                violations.append(f"{relative}: legacy SEC import")
            elif "LEGACY-FUNDAMENTAL-MIGRATION-EVIDENCE" not in source:
                violations.append(f"{relative}: missing quarantine marker")

    assert not violations, "Unquarantined legacy SEC scripts found:\n" + "\n".join(
        sorted(violations)
    )


def test_no_legacy_fundamental_state_keys_in_runtime_source() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    source_root = repo_root / "finance-agent-core" / "src" / "agents" / "fundamental"
    banned_keys = ("financial_reports_artifact_id",)
    violations: list[str] = []
    for path in source_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for key in banned_keys:
            if key in source:
                violations.append(f"{path.relative_to(repo_root)}: {key}")

    assert not violations, "Legacy Fundamental state keys found:\n" + "\n".join(
        sorted(violations)
    )


def test_release_gate_has_no_retired_replay_manifest_surface() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    retired_flag = "FUNDAMENTAL_REPLAY_MANIFEST_PATH"
    paths = (
        repo_root
        / "finance-agent-core"
        / "scripts"
        / "run_fundamental_release_gate.sh",
        repo_root / "finance-agent-core" / "docs" / "fundamental_backtest_runbook.md",
    )
    violations = [
        f"{path.relative_to(repo_root)}: {retired_flag}"
        for path in paths
        if retired_flag in path.read_text(encoding="utf-8")
    ]
    assert not violations, "Retired replay manifest flag found:\n" + "\n".join(
        violations
    )


def test_frontend_has_no_agent_sec_or_legacy_fundamental_fallbacks() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    frontend_root = repo_root / "frontend" / "src"
    banned_tokens = (
        "financial_reports_artifact_id",
        "replay_source_reports_artifact_id",
        "reports_artifact_id",
        "raw_financial_reports",
        "fetch_financial_reports_payload",
        "sec_xbrl",
    )
    violations: list[str] = []
    for path in frontend_root.rglob("*"):
        if path.suffix not in {".ts", ".tsx"} or not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        for token in banned_tokens:
            if token in source:
                violations.append(f"{path.relative_to(repo_root)}: {token}")

    assert not violations, "Legacy Fundamental browser fallbacks found:\n" + "\n".join(
        sorted(violations)
    )


def test_calibration_fixtures_are_versioned_and_allowlisted() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    fixtures_root = repo_root / "finance-agent-core" / "tests" / "fixtures"
    calibration_fixtures = sorted(
        path
        for path in fixtures_root.rglob("*")
        if path.is_file() and "calibr" in path.name.lower()
    )
    expected_fixture = (
        fixtures_root / "forward_signal_calibration_pipeline_replay_fixture.json"
    )
    assert calibration_fixtures == [expected_fixture], (
        "Unversioned or duplicate Fundamental calibration fixtures found:\n"
        + "\n".join(str(path.relative_to(repo_root)) for path in calibration_fixtures)
    )

    payload = json.loads(expected_fixture.read_text(encoding="utf-8"))
    assert payload.get("fixture_version") == "forward_signal_calibration_pipeline_v1"
    assert isinstance(payload.get("results"), list) and payload["results"]
