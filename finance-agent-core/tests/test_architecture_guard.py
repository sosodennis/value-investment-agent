from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "architecture_guard.py"
SPEC = importlib.util.spec_from_file_location("architecture_guard", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load architecture guard from {SCRIPT_PATH}")
architecture_guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = architecture_guard
SPEC.loader.exec_module(architecture_guard)


def _write_module(src_root: Path, module: str, source: str) -> None:
    relative_parts = module.removeprefix("src.").split(".")
    path = src_root.joinpath(*relative_parts).with_suffix(".py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_guard_detects_forbidden_layer_direction(tmp_path: Path) -> None:
    src_root = tmp_path / "src"
    _write_module(
        src_root,
        "src.agents.intent.domain.policy",
        "from src.agents.intent.infrastructure.provider import Provider\n",
    )

    violations = architecture_guard.collect_violations(src_root)

    assert [(item.rule, item.source, item.target) for item in violations] == [
        (
            "LAYER_DIRECTION",
            "src.agents.intent.domain.policy",
            "src.agents.intent.infrastructure.provider",
        )
    ]


def test_guard_covers_new_agent_names_without_registry_changes(tmp_path: Path) -> None:
    src_root = tmp_path / "src"
    _write_module(
        src_root,
        "src.agents.portfolio.application.runner",
        "from src.agents.portfolio.infrastructure.provider import Provider\n",
    )

    violations = architecture_guard.collect_violations(src_root)

    assert [(item.rule, item.source, item.target) for item in violations] == [
        (
            "LAYER_DIRECTION",
            "src.agents.portfolio.application.runner",
            "src.agents.portfolio.infrastructure.provider",
        )
    ]


def test_guard_rejects_agent_dependency_on_root_workflow(tmp_path: Path) -> None:
    src_root = tmp_path / "src"
    _write_module(
        src_root,
        "src.agents.intent.application.runner",
        "from src.workflow.graph import build_graph\n",
    )

    violations = architecture_guard.collect_violations(src_root)

    assert [(item.rule, item.source, item.target) for item in violations] == [
        (
            "LAYER_DIRECTION",
            "src.agents.intent.application.runner",
            "src.workflow.graph",
        )
    ]


def test_guard_allows_entrypoint_to_use_own_wiring_factory(tmp_path: Path) -> None:
    src_root = tmp_path / "src"
    _write_module(
        src_root,
        "src.agents.intent.entrypoint",
        "from src.agents.intent.application.wiring import build_default_runner\n",
    )
    _write_module(
        src_root,
        "src.agents.intent.application.wiring",
        "def build_default_runner(): pass\n",
    )

    violations = architecture_guard.collect_violations(src_root)

    assert violations == []


@pytest.mark.parametrize(
    ("module", "source", "expected_rule"),
    [
        (
            "src.agents.intent.entrypoint",
            "from src.agents.intent.infrastructure.provider import Provider\n",
            "LAYER_DIRECTION",
        ),
        (
            "src.agents.intent.entrypoint",
            "from src.agents.intent.application.composition import build_runner\n",
            "LAYER_DIRECTION",
        ),
        (
            "src.agents.intent.entrypoint",
            "from src.agents.intent.application.wiring.factory import build_runner\n",
            "LAYER_DIRECTION",
        ),
        (
            "src.agents.intent.entrypoint",
            "from src.workflow.graph import build_graph\n",
            "LAYER_DIRECTION",
        ),
        (
            "src.agents.intent.entrypoint",
            "from src.agents.news.application.runner import Runner\n",
            "CROSS_AGENT_PRIVATE_IMPORT",
        ),
        (
            "src.agents.intent.entrypoint",
            "from src.agents.news.application.wiring import build_runner\n",
            "CROSS_AGENT_PRIVATE_IMPORT",
        ),
        (
            "src.agents.intent.application.runner",
            "from src.agents.intent.entrypoint import run_graph\n",
            "LAYER_DIRECTION",
        ),
    ],
)
def test_guard_preserves_entrypoint_and_application_boundaries(
    tmp_path: Path, module: str, source: str, expected_rule: str
) -> None:
    src_root = tmp_path / "src"
    _write_module(src_root, module, source)

    rules = {item.rule for item in architecture_guard.collect_violations(src_root)}

    assert expected_rule in rules


def test_guard_rejects_root_and_cross_agent_private_imports(tmp_path: Path) -> None:
    src_root = tmp_path / "src"
    _write_module(
        src_root,
        "src.workflow.graph",
        "from src.agents.intent.application.orchestrator import run\n",
    )
    _write_module(
        src_root,
        "src.agents.debate.domain.policy",
        "from src.agents.fundamental.domain.policy import Policy\n",
    )

    rules = {item.rule for item in architecture_guard.collect_violations(src_root)}

    assert "ROOT_WORKFLOW_PRIVATE_IMPORT" in rules
    assert "CROSS_AGENT_PRIVATE_IMPORT" in rules


def test_guard_detects_private_capability_import_and_cycle(tmp_path: Path) -> None:
    src_root = tmp_path / "src"
    _write_module(
        src_root,
        "src.agents.technical.capabilities.features.domain.api",
        "from src.agents.technical.capabilities.patterns.domain.detector import detect\n",
    )
    _write_module(
        src_root,
        "src.agents.technical.capabilities.patterns.domain.detector",
        "from src.agents.technical.capabilities.features.domain.api import Feature\n",
    )

    violations = architecture_guard.collect_violations(src_root)
    rules = {item.rule for item in violations}

    assert "CAPABILITY_PRIVATE_IMPORT" in rules
    assert "CAPABILITY_CYCLE" in rules


def test_guard_accepts_capability_facade_import(tmp_path: Path) -> None:
    src_root = tmp_path / "src"
    _write_module(
        src_root,
        "src.agents.technical.application.runner",
        "from src.agents.technical.capabilities.features import FeatureRuntime\n",
    )

    violations = architecture_guard.collect_violations(src_root)

    assert violations == []


def test_exception_must_reference_its_module_action() -> None:
    key = (
        "LAYER_DIRECTION|src.agents.intent.domain.policy|"
        "src.agents.intent.infrastructure.provider"
    )

    assert (
        architecture_guard.validate_exception_actions(
            {key: "INTENT-CORE"}, {"INTENT-CORE"}
        )
        == []
    )
    assert architecture_guard.validate_exception_actions(
        {key: "NEWS-CORE"}, {"NEWS-CORE"}
    ) == [f"{key} maps to NEWS-CORE, expected INTENT-CORE for its source module"]
    assert architecture_guard.validate_exception_actions(
        {key: "INTENT-CORE"}, set()
    ) == [f"{key} references missing report action INTENT-CORE"]


def test_guard_fails_for_new_and_stale_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    src_root = tmp_path / "src"
    _write_module(
        src_root,
        "src.agents.intent.domain.policy",
        "from src.agents.intent.infrastructure.provider import Provider\n",
    )
    exceptions_dir = tmp_path / "exceptions"
    report = tmp_path / "actions.md"
    report.write_text("### [INTENT-CORE] Module remediation\n", encoding="utf-8")
    collect_violations = architecture_guard.collect_violations
    monkeypatch.setattr(
        architecture_guard,
        "collect_violations",
        lambda: collect_violations(src_root),
    )
    monkeypatch.setattr(architecture_guard, "EXCEPTIONS_DIR", exceptions_dir)
    monkeypatch.setattr(architecture_guard, "REPORT_PATH", report)

    assert architecture_guard.main([]) == 1
    assert "unapproved dependency violations" in capsys.readouterr().out

    exceptions_dir.mkdir()
    (exceptions_dir / "src.agents.intent.domain.old.tsv").write_text(
        "LAYER_DIRECTION|src.agents.intent.domain.old|"
        "src.agents.intent.infrastructure.old|INTENT-CORE\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(architecture_guard, "collect_violations", lambda: [])

    assert architecture_guard.main([]) == 1
    assert "stale exceptions" in capsys.readouterr().out


def test_exception_shards_require_source_module_filename(tmp_path: Path) -> None:
    shard = tmp_path / "wrong-source.tsv"
    shard.write_text(
        "LAYER_DIRECTION|src.agents.intent.domain.policy|"
        "src.agents.intent.infrastructure.provider|INTENT-CORE\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError, match="belongs in src.agents.intent.domain.policy.tsv"
    ):
        architecture_guard.load_exceptions(tmp_path)


def test_exception_shards_reject_duplicate_records(tmp_path: Path) -> None:
    record = (
        "LAYER_DIRECTION|src.agents.intent.domain.policy|"
        "src.agents.intent.infrastructure.provider|INTENT-CORE\n"
    )
    shard = tmp_path / "src.agents.intent.domain.policy.tsv"
    shard.write_text(record + record, encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate exception"):
        architecture_guard.load_exceptions(tmp_path)


def test_cycle_findings_use_the_scanned_capability_root(tmp_path: Path) -> None:
    src_root = tmp_path / "src"
    _write_module(
        src_root,
        "src.agents.technical.capabilities.alpha.domain.api",
        "from src.agents.technical.capabilities.beta.domain.api import Value\n",
    )
    _write_module(
        src_root,
        "src.agents.technical.capabilities.beta.domain.api",
        "from src.agents.technical.capabilities.alpha.domain.api import Value\n",
    )

    cycles = [
        item
        for item in architecture_guard.collect_violations(src_root)
        if item.rule == "CAPABILITY_CYCLE"
    ]

    assert cycles
    assert all(".capabilities." in item.source for item in cycles)
    assert all(".capabilities." in item.target for item in cycles)
