"""Conditional research has durable identities without becoming a valuation release."""

import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from fundamental_service import enterprise_research_runner as runner
from fundamental_service.enterprise_research import research_enterprise_value
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_enterprise_research import request, scenario

REVISION = "a" * 40


def inventory(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


def test_persistent_output_is_official_and_reopened_repeat_never_writes(tmp_path):
    value = request(data_release_manifest_digest=None)
    store = ArtifactStore(tmp_path)
    first = runner.persist_enterprise_research(
        value, source_revision=REVISION, artifacts=store
    )
    assert first.wrote
    assert first.output_digest == research_enterprise_value(value).output_digest
    assert store.read(first.execution.result_ref.artifact_id) == canonical_bytes(
        research_enterprise_value(value)
    )
    assert store.read(first.execution.request_ref.artifact_id) == canonical_bytes(value)
    assert store.read(first.execution_ref.artifact_id) == canonical_bytes(
        first.execution
    )
    assert first.execution.input.declared_source_revision == REVISION
    assert (
        first.execution.input.installed_source_digest
        == runner.installed_research_runtime()[0]
    )
    assert first.execution.input.runtime_pins["python"]
    assert first.input_digest == sha256_digest(first.execution.input)
    before = inventory(tmp_path)
    second = runner.persist_enterprise_research(
        value.model_copy(update={"facts": tuple(reversed(value.facts))}),
        source_revision=REVISION,
        artifacts=ArtifactStore(tmp_path),
    )
    assert second == first.model_copy(update={"wrote": False})
    assert inventory(tmp_path) == before
    assert (
        json.loads(store.read(first.execution.result_ref.artifact_id))[
            "operating_forecast"
        ]["data_release_manifest_digest"]
        is None
    )


def test_abstentions_are_persisted_with_successful_siblings(tmp_path):
    value = request(
        scenarios=(scenario(), scenario("invalid", terminal_growth=Decimal("0.5")))
    )
    store = ArtifactStore(tmp_path)
    receipt = runner.persist_enterprise_research(
        value, source_revision=REVISION, artifacts=store
    )
    result = json.loads(store.read(receipt.execution.result_ref.artifact_id))
    assert [row["status"] for row in result["results"]] == [
        "provisional_conditional_enterprise_value",
        "abstained",
    ]
    assert result["results"][1]["issue_codes"]
    assert result["supported_history_threshold"] is None
    assert "caller_approval" in result["unestablished_claims"]


def test_concurrent_reopened_stores_publish_one_identity(tmp_path):
    value = request()

    def publish(_):
        return runner.persist_enterprise_research(
            value, source_revision=REVISION, artifacts=ArtifactStore(tmp_path)
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(publish, range(8)))
    assert any(r.wrote for r in receipts)
    assert len({r.execution_ref.content_hash for r in receipts}) == 1
    records = (tmp_path / ".artifact-records.jsonl").read_text().splitlines()
    assert len(records) == 3
    assert not publish(None).wrote


@pytest.mark.parametrize("change", ("revision", "runtime", "source", "request"))
def test_execution_identity_binds_runtime_source_revision_and_request(
    tmp_path, monkeypatch, change
):
    value = request()
    store = ArtifactStore(tmp_path)
    first = runner.persist_enterprise_research(
        value, source_revision=REVISION, artifacts=store
    )
    original_source, pins = runner.installed_research_runtime()
    revision = REVISION
    if change == "revision":
        revision = "b" * 40
    elif change == "runtime":
        monkeypatch.setattr(
            runner,
            "installed_research_runtime",
            lambda: (original_source, {**pins, "python": "different"}),
        )
    elif change == "source":
        monkeypatch.setattr(
            runner, "installed_research_runtime", lambda: ("b" * 64, pins)
        )
    else:
        value = request(mapping_version="different-reference")
    second = runner.persist_enterprise_research(
        value, source_revision=revision, artifacts=store
    )
    assert second.wrote and second.input_digest != first.input_digest
    assert second.execution_ref != first.execution_ref
    assert store.read(first.execution_ref.artifact_id) == canonical_bytes(
        first.execution
    )
    if change != "request":
        assert second.execution.result_ref == first.execution.result_ref


def test_interrupted_publication_resumes_without_rewriting_existing_input(tmp_path):
    value = request()

    class InterruptedStore(ArtifactStore):
        def put_with_receipt(self, artifact_id, *args, **kwargs):
            if artifact_id.startswith("enterprise-research-result:"):
                raise ConnectionError("interrupted after input publication")
            return super().put_with_receipt(artifact_id, *args, **kwargs)

    with pytest.raises(ConnectionError):
        runner.persist_enterprise_research(
            value, source_revision=REVISION, artifacts=InterruptedStore(tmp_path)
        )
    before = {k: v for k, v in inventory(tmp_path).items() if k.endswith(".artifact")}
    resumed = runner.persist_enterprise_research(
        value, source_revision=REVISION, artifacts=ArtifactStore(tmp_path)
    )
    assert resumed.wrote
    after = inventory(tmp_path)
    assert all(after[k] == v for k, v in before.items())
    assert not runner.persist_enterprise_research(
        value, source_revision=REVISION, artifacts=ArtifactStore(tmp_path)
    ).wrote


def test_corrupt_published_result_refuses_without_repair(tmp_path):
    store = ArtifactStore(tmp_path)
    value = request()
    first = runner.persist_enterprise_research(
        value, source_revision=REVISION, artifacts=store
    )
    path = next(tmp_path.glob(first.output_digest + ".*.artifact"))
    path.write_bytes(b"corrupt")
    before = inventory(tmp_path)
    with pytest.raises(SnapshotError, match="verification"):
        runner.persist_enterprise_research(
            value, source_revision=REVISION, artifacts=store
        )
    assert inventory(tmp_path) == before


@pytest.mark.parametrize(
    "change", ("digest", "canonical", "duplicate", "model", "revision")
)
def test_invalid_cli_input_is_rejected_before_opening_storage(
    tmp_path, monkeypatch, capsys, change
):
    value = request()
    raw = canonical_bytes(value)
    digest = sha256_digest(value)
    revision = REVISION
    if change == "digest":
        digest = "0" * 64
    elif change == "canonical":
        raw += b"\n"
    elif change == "duplicate":
        raw = b'{"model_id":"discarded",' + raw[1:]
    elif change == "model":
        value = value.model_copy(update={"model_version": "fcff_dcf-v999"})
        raw, digest = canonical_bytes(value), sha256_digest(value)
    else:
        revision = "not-a-revision"
    path = tmp_path / "request.json"
    path.write_bytes(raw)

    def forbidden(*args, **kwargs):
        pytest.fail("invalid input opened storage")

    monkeypatch.setattr(runner, "command_artifacts", forbidden)
    assert (
        runner.main(
            [
                "--request",
                str(path),
                "--request-digest",
                digest,
                "--source-revision",
                revision,
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err)["error_code"] == "ENTERPRISE_RESEARCH_INPUT_INVALID"


def test_cli_offline_repeat_uses_same_persistent_artifacts(tmp_path, capsys):
    value = request()
    path = tmp_path / "request.json"
    path.write_bytes(canonical_bytes(value))
    args = [
        "--request",
        str(path),
        "--request-digest",
        sha256_digest(value),
        "--source-revision",
        REVISION,
        "--artifacts-root",
        str(tmp_path / "store"),
    ]
    assert runner.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    before = inventory(tmp_path)
    assert runner.main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert first["wrote"] and not second["wrote"]
    assert {k: v for k, v in first.items() if k != "wrote"} == {
        k: v for k, v in second.items() if k != "wrote"
    }
    assert inventory(tmp_path) == before


def test_unconfigured_default_storage_never_falls_back_to_local_cache(
    tmp_path, monkeypatch, capsys
):
    for name in ("FUNDAMENTAL_SERVICE_DATABASE_URL", "FUNDAMENTAL_SERVICE_DATA_ROOT"):
        monkeypatch.delenv(name, raising=False)
    value = request()
    path = tmp_path / "request.json"
    path.write_bytes(canonical_bytes(value))
    before = inventory(tmp_path)
    assert (
        runner.main(
            [
                "--request",
                str(path),
                "--request-digest",
                sha256_digest(value),
                "--source-revision",
                REVISION,
            ]
        )
        == 2
    )
    assert (
        json.loads(capsys.readouterr().err)["error_code"]
        == "EVIDENCE_STORAGE_UNCONFIGURED"
    )
    assert inventory(tmp_path) == before
