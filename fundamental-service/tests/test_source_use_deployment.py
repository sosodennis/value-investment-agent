"""Deployment configuration cannot silently add or retain source-use grants."""

import pytest

from fundamental_service.app import create_runtime_app
from fundamental_service.free_source_policy import free_market_source_policy
from fundamental_service.issuer_preparation_runner import _run_module
from fundamental_service.source_admission import SourceUsePolicyV1
from fundamental_service.source_use_deployment import load_runtime_source_use_policy
from test_yahoo_quote_preparation import policy as synthetic_quote_policy

FILE_ENV = "FUNDAMENTAL_SOURCE_USE_POLICY_FILE"
DIGEST_ENV = "FUNDAMENTAL_SOURCE_USE_POLICY_DIGEST"


@pytest.fixture(autouse=True)
def isolated_policy_environment(monkeypatch):
    monkeypatch.delenv(FILE_ENV, raising=False)
    monkeypatch.delenv(DIGEST_ENV, raising=False)


def configure(monkeypatch, tmp_path, policy):
    path = tmp_path / "deployment-policy.json"
    path.write_text(policy.model_dump_json(indent=2))
    monkeypatch.setenv(FILE_ENV, str(path))
    monkeypatch.setenv(DIGEST_ENV, policy.digest)
    return path


def test_unconfigured_deployment_keeps_default_without_quote_grant():
    selected = load_runtime_source_use_policy()
    assert selected == free_market_source_policy()
    assert not any(rule.metric_id == "common_share.price" for rule in selected.rules)


@pytest.mark.parametrize("revoked", [False, True])
def test_runtime_uses_complete_pinned_catalog_without_inherited_grants(
    monkeypatch, tmp_path, revoked
):
    selected = (
        SourceUsePolicyV1(policy_version="synthetic-revocation-v1")
        if revoked
        else synthetic_quote_policy()
    )
    configure(monkeypatch, tmp_path, selected)
    monkeypatch.delenv("FUNDAMENTAL_SERVICE_DATA_ROOT", raising=False)
    monkeypatch.delenv("FUNDAMENTAL_SERVICE_DATABASE_URL", raising=False)

    application = create_runtime_app().state.application

    assert application.source_use_policy == selected
    assert application.source_use_policy.digest == selected.digest
    assert application.source_use_policy.rules == selected.rules


@pytest.mark.parametrize(
    "file_value,digest",
    [(None, "a" * 64), ("/missing", None), ("", "a" * 64), ("/missing", "")],
)
def test_partial_configuration_refuses_instead_of_falling_back(
    monkeypatch, file_value, digest
):
    if file_value is not None:
        monkeypatch.setenv(FILE_ENV, file_value)
    if digest is not None:
        monkeypatch.setenv(DIGEST_ENV, digest)
    with pytest.raises(ValueError, match="requires both deployment file and digest"):
        load_runtime_source_use_policy()


@pytest.mark.parametrize(
    "content", [None, b"not JSON private-secret", b'{"secret":"private-secret"}']
)
def test_invalid_deployment_fails_without_echoing_content(
    monkeypatch, tmp_path, content
):
    path = tmp_path / "private-secret-policy.json"
    if content is not None:
        path.write_bytes(content)
    monkeypatch.setenv(FILE_ENV, str(path))
    monkeypatch.setenv(DIGEST_ENV, "a" * 64)

    with pytest.raises(ValueError) as error:
        create_runtime_app()

    assert str(error.value) == "source-use deployment policy is unreadable or invalid"
    assert error.value.__suppress_context__


def test_replaced_policy_with_same_version_requires_new_digest(monkeypatch, tmp_path):
    selected = synthetic_quote_policy()
    path = configure(monkeypatch, tmp_path, selected)
    path.write_text(
        SourceUsePolicyV1(policy_version=selected.policy_version).model_dump_json()
    )

    with pytest.raises(ValueError, match="deployment policy digest differs"):
        create_runtime_app()


def test_actual_issuer_child_inherits_policy_pin_before_reading_plan(
    monkeypatch, tmp_path
):
    configure(monkeypatch, tmp_path, synthetic_quote_policy())
    monkeypatch.setenv(DIGEST_ENV, "a" * 64)
    absent_plan = tmp_path / "private-plan.json"

    result = _run_module(
        "fundamental_service.preparation_runner",
        [
            "--plan",
            str(absent_plan),
            "--plan-digest",
            "b" * 64,
            "--actor",
            "synthetic-operator",
            "--organization",
            "synthetic-research",
        ],
        timeout_seconds=20,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == (
        "source preparation failed: source-use deployment policy digest differs\n"
    )
    assert not absent_plan.exists()


def test_canary_rejects_bad_policy_before_candidate_io(monkeypatch, tmp_path, capsys):
    from fundamental_service.release_runner import main

    configure(monkeypatch, tmp_path, synthetic_quote_policy())
    monkeypatch.setenv(DIGEST_ENV, "a" * 64)
    arguments = []
    for flag in (
        "--candidate",
        "--snapshots-root",
        "--facts-root",
        "--mappings-root",
        "--artifacts-root",
        "--trust-roots",
    ):
        arguments.extend((flag, str(tmp_path / "absent")))

    assert main(arguments) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "data release canary failed: source-use deployment policy digest differs\n"
    )
    assert not (tmp_path / "absent").exists()
