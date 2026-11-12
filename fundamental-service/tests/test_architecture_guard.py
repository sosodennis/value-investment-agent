from pathlib import Path

import pytest

from fundamental_service.architecture_guard import check


def test_fundamental_service_boundary_has_no_legacy_auth_or_agent_imports():
    root = Path(__file__).resolve().parents[1]
    assert check(root) == []


def test_guard_excludes_third_party_environment_sources(tmp_path):
    dependency = tmp_path / ".venv/lib/site-packages/dependency.py"
    dependency.parent.mkdir(parents=True)
    dependency.write_bytes(b"# coding: cp1252\nmessage = '\x93vendor\x94'\n")
    owned = tmp_path / "src/package.py"
    owned.parent.mkdir()
    owned.write_text("import decimal\n")
    assert check(tmp_path) == []


@pytest.mark.parametrize("directory", ["src", "tests", "scripts"])
@pytest.mark.parametrize(
    "statement",
    [
        "import agents.private",
        "import decimal, agents.private",
        "from finance_agent_core import internal",
    ],
)
def test_guard_still_rejects_forbidden_imports_in_every_owned_root(
    tmp_path, directory, statement
):
    source = tmp_path / directory / "owned.py"
    source.parent.mkdir()
    source.write_text(statement + "\n")
    assert len(check(tmp_path)) == 1
    assert "forbidden import" in check(tmp_path)[0]


def test_guard_retains_legacy_marker_and_docker_composition_checks(tmp_path):
    source = tmp_path / "src/owned.py"
    source.parent.mkdir()
    source.write_text("def require" + "_auth(): pass\n")
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
    failures = check(tmp_path)
    assert any("legacy authentication marker" in failure for failure in failures)
    assert any("internal-contract package" in failure for failure in failures)
