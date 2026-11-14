from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import validate_compose_inputs as validator


def _compose(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "compose.yml"
    path.write_text(body, encoding="utf-8")
    return path


def _env(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    return path


def test_reports_all_missing_required_variables(tmp_path: Path, monkeypatch) -> None:
    compose = _compose(
        tmp_path,
        "services:\n  app:\n    image: example\n    environment:\n      A: ${A:?required}\n      B: ${B:?required}\n",
    )
    env_file = _env(tmp_path, "")
    monkeypatch.delenv("A", raising=False)
    monkeypatch.delenv("B", raising=False)

    errors = validator.validate(
        label="app",
        env_file=env_file,
        compose_files=[compose],
        require_paths=False,
        require_sec_user_agent=False,
    )

    assert errors == [
        "app: missing required Compose variable A",
        "app: missing required Compose variable B",
    ]


def test_rejects_shell_override_of_recorded_env(tmp_path: Path, monkeypatch) -> None:
    compose = _compose(
        tmp_path,
        "services:\n  app:\n    image: example\n    environment:\n      A: ${A:?required}\n",
    )
    env_file = _env(tmp_path, "A=from-file\n")
    monkeypatch.setenv("A", "from-shell")

    errors = validator.validate(
        label="app",
        env_file=env_file,
        compose_files=[compose],
        require_paths=False,
        require_sec_user_agent=False,
    )

    assert any("shell environment overrides A" in error for error in errors)


def test_rejects_required_value_supplied_only_by_shell(
    tmp_path: Path, monkeypatch
) -> None:
    compose = _compose(
        tmp_path,
        "services:\n  app:\n    image: example\n    environment:\n      A: ${A:?required}\n",
    )
    env_file = _env(tmp_path, "")
    monkeypatch.setenv("A", "from-shell")

    errors = validator.validate(
        label="app",
        env_file=env_file,
        compose_files=[compose],
        require_paths=False,
        require_sec_user_agent=False,
    )

    assert any("shell-only Compose variable A" in error for error in errors)


def test_rejects_placeholder_sec_user_agent(tmp_path: Path, monkeypatch) -> None:
    compose = _compose(tmp_path, "services:\n  app:\n    image: example\n")
    env_file = _env(
        tmp_path,
        'FUNDAMENTAL_SEC_USER_AGENT="ValueInvestmentAgent/1.0 (contact@example.com)"\n',
    )
    monkeypatch.delenv("FUNDAMENTAL_SEC_USER_AGENT", raising=False)

    errors = validator.validate(
        label="fundamental",
        env_file=env_file,
        compose_files=[compose],
        require_paths=False,
        require_sec_user_agent=True,
    )

    assert any("non-placeholder contact string" in error for error in errors)


def test_ordered_env_files_use_last_value_and_reject_shell_drift(tmp_path, monkeypatch):
    compose = _compose(tmp_path, "services:\n  app:\n    image: ${A:?required}\n")
    first = _env(tmp_path, "A=first\n")
    second = tmp_path / "overlay.env"
    second.write_text("A=last\n")
    monkeypatch.setenv("A", "last")
    args = dict(
        label="fundamental",
        env_file=None,
        env_files=[first, second],
        compose_files=[compose],
        require_paths=False,
        require_sec_user_agent=False,
    )
    assert validator.validate(**args) == []
    monkeypatch.setenv("A", "first")
    assert any(
        "shell environment overrides A" in error for error in validator.validate(**args)
    )
