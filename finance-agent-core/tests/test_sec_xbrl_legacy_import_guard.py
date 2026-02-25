from __future__ import annotations

from pathlib import Path


def test_no_legacy_sec_xbrl_shim_imports_used() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scan_roots = [
        repo_root / "finance-agent-core" / "src",
        repo_root / "finance-agent-core" / "tests",
        repo_root / "finance-agent-core" / "scripts",
    ]
    legacy_prefix = "src.agents.fundamental.data.clients.sec_xbrl"
    banned_absolute_imports = tuple(
        f"{legacy_prefix}.{name}"
        for name in (
            "regex_signal_extractor",
            "lemma_signal_matcher",
            "dependency_signal_matcher",
            "signal_pattern_catalog",
        )
    )

    violations: list[str] = []
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path.name == "test_sec_xbrl_legacy_import_guard.py":
                continue
            content = path.read_text(encoding="utf-8")
            for banned in banned_absolute_imports:
                if banned in content:
                    relative_path = path.relative_to(repo_root)
                    violations.append(f"{relative_path}: {banned}")

    assert not violations, "Legacy sec_xbrl shim imports found:\n" + "\n".join(
        sorted(violations)
    )
