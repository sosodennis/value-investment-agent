"""Automatic preparation reads the facts retained by its exact acquisitions."""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from fundamental_service.facts import FilesystemCanonicalFactRepository
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresCanonicalFactRepository,
    PostgresContentStore,
    PostgresMetadataStore,
    PostgresSnapshotRepository,
)
from fundamental_service.preparation_runner import (
    SourcePreparationEvidenceV1,
    SourcePreparationRunner,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_automatic_source_acquisition import acquisition_case, acquire
from test_automatic_source_preparation import automatic_plan


@pytest.fixture(params=("filesystem", "postgres"))
def plan_facts_case(tmp_path, monkeypatch, request):
    metadata = None
    kwargs = {}
    if request.param == "postgres":
        database, _ = request.getfixturevalue("recovery_databases")
        metadata = PostgresMetadataStore(database, auto_migrate=True)
        metadata.start()
        content = PostgresContentStore(tmp_path / "content", metadata)
        kwargs = {
            "metadata": metadata,
            "content": content,
            "artifacts": PostgresArtifactStore(metadata, content),
            "repository": PostgresSnapshotRepository(metadata),
        }
        facts = PostgresCanonicalFactRepository(metadata)
    else:
        facts = FilesystemCanonicalFactRepository(tmp_path / "facts")
    try:
        source_request, acquisition, state, reader, artifacts = acquisition_case(
            tmp_path, monkeypatch, **kwargs
        )
        if metadata is None:
            publish = reader.publish_sec_ingestion

            def retain_facts(**value):
                for fact in value["facts"]:
                    facts.publish(fact)
                return publish(**value)

            monkeypatch.setattr(reader, "publish_sec_ingestion", retain_facts)
        retained = acquire(source_request, acquisition)
        snapshot = (
            metadata.get_snapshot(retained.snapshot_id)
            if metadata is not None
            else reader.snapshots[retained.snapshot_id]
        )
        application = SimpleNamespace(
            fact_repository=facts,
            artifact_store=artifacts,
            snapshot=lambda snapshot_id: snapshot,
        )
        runner = SourcePreparationRunner(
            application=application,
            metadata=reader,
            acquisition=acquisition,
            artifacts=artifacts,
            canary=None,
        )

        def change_payload(fact_id, payload):
            if metadata is None:
                path = facts.root / (fact_id + ".json")
                if payload is None:
                    path.unlink()
                else:
                    path.write_bytes(canonical_bytes(payload))
            else:

                async def mutate():
                    async with metadata._runner._engine.begin() as connection:
                        if payload is None:
                            await connection.execute(
                                text(
                                    "DELETE FROM fundamental.snapshot_facts "
                                    "WHERE fact_id=:id"
                                ),
                                {"id": fact_id},
                            )
                        await connection.execute(
                            text(
                                "DELETE FROM fundamental.canonical_facts "
                                "WHERE fact_id=:id"
                                if payload is None
                                else "UPDATE fundamental.canonical_facts "
                                "SET payload=CAST(:payload AS jsonb) WHERE fact_id=:id"
                            ),
                            {"id": fact_id, "payload": json.dumps(payload)},
                        )

                metadata._runner.run(mutate())

        yield SimpleNamespace(
            runner=runner,
            plan=automatic_plan(source_request),
            snapshot=snapshot,
            facts=facts,
            retained=retained,
            state=state,
            change_payload=change_payload,
        )
    finally:
        if metadata is not None:
            metadata.close()


def test_automatic_plan_excludes_unretained_facts_even_with_same_source_and_mapping(
    plan_facts_case,
):
    case = plan_facts_case
    expected = case.runner._plan_facts(case.plan, case.snapshot)
    assert {fact.fact_id for fact in expected} == set(case.retained.canonical_fact_ids)
    unrelated = expected[0].model_copy(update={"fact_id": "unretained-fact"})
    case.facts.publish(unrelated)
    calls = case.state.provider_calls, case.state.parser_calls
    assert case.runner._plan_facts(case.plan, case.snapshot) == expected
    case.change_payload(unrelated.fact_id, {"fact_id": unrelated.fact_id})
    assert case.runner._plan_facts(case.plan, case.snapshot) == expected
    assert calls == (case.state.provider_calls, case.state.parser_calls)


def test_fact_selection_validates_each_acquisition_once_and_rechecks_next_read(
    plan_facts_case, monkeypatch
):
    case = plan_facts_case
    acquisition = case.runner._acquisition
    retained = acquisition.retained_acquisition
    requests = []

    def observed(request):
        requests.append(request)
        return retained(request)

    monkeypatch.setattr(acquisition, "retained_acquisition", observed)
    first = case.runner._plan_facts(case.plan, case.snapshot)
    assert requests == list(case.plan.ingestions)
    assert first
    requests.clear()
    assert case.runner._plan_facts(case.plan, case.snapshot) == first
    assert requests == list(case.plan.ingestions)
    case.change_payload(first[0].fact_id, None)
    with pytest.raises(SnapshotError) as error:
        case.runner._plan_facts(case.plan, case.snapshot)
    assert error.value.code == "FACT_NOT_FOUND"


def test_history_and_flow_publication_consume_prepared_stage_output(
    plan_facts_case, monkeypatch
):
    case = plan_facts_case
    expected_history = case.runner._assess_history_requirements(
        case.plan, case.snapshot
    )
    evidence = SourcePreparationEvidenceV1(
        source_revision=case.plan.source_revision,
        plan_digest=case.plan.digest,
        status="blocked",
        snapshot_id=case.snapshot.snapshot_id,
        snapshot_manifest_digest=case.snapshot.manifest_digest,
        issue_codes=("DATA_RELEASE_REQUIRED",),
    )
    expected = case.runner._persist(case.plan, evidence)
    prepared = case.runner._prepare_plan_facts(case.plan, case.snapshot)

    def repeated_selection(*args, **kwargs):
        pytest.fail("the next stage must consume its checked mappings and facts")

    monkeypatch.setattr(case.runner, "_plan_mappings", repeated_selection)
    monkeypatch.setattr(case.runner, "_plan_facts", repeated_selection)
    assert (
        case.runner._assess_history_requirements(
            case.plan, case.snapshot, prepared_facts=prepared
        )
        == expected_history
    )
    reused = case.runner._persist(case.plan, evidence, prepared_facts=prepared)
    assert reused.artifact == expected.artifact and not reused.wrote


@pytest.mark.parametrize("changed_scope", ("plan", "snapshot"))
def test_prepared_stage_output_refuses_a_different_plan_or_snapshot(
    plan_facts_case, changed_scope
):
    case = plan_facts_case
    prepared = case.runner._prepare_plan_facts(case.plan, case.snapshot)
    plan, snapshot = case.plan, case.snapshot
    if changed_scope == "plan":
        plan = plan.model_copy(update={"release_profile_id": "another-profile"})
    else:
        snapshot = snapshot.model_copy(update={"manifest_digest": "f" * 64})
    with pytest.raises(ValueError, match="exact plan and snapshot"):
        case.runner._assess_history_requirements(
            plan, snapshot, prepared_facts=prepared
        )


def test_flow_publication_reselects_facts_after_resolved_snapshot_changes(
    plan_facts_case, monkeypatch
):
    case = plan_facts_case
    prepared = case.runner._prepare_plan_facts(case.plan, case.snapshot)
    payload = case.snapshot.model_dump(exclude={"manifest_digest", "snapshot_id"})
    payload["captured_at"] += timedelta(seconds=1)
    replacement = type(case.snapshot)(
        **payload,
        snapshot_id=case.snapshot.snapshot_id + "-replacement",
        manifest_digest=sha256_digest(payload),
    )
    monkeypatch.setattr(
        case.runner._application,
        "snapshot",
        {
            case.snapshot.snapshot_id: case.snapshot,
            replacement.snapshot_id: replacement,
        }.__getitem__,
    )
    evidence = SourcePreparationEvidenceV1(
        source_revision=case.plan.source_revision,
        plan_digest=case.plan.digest,
        status="release_required",
        snapshot_id=replacement.snapshot_id,
        snapshot_manifest_digest=replacement.manifest_digest,
        issue_codes=("DATA_RELEASE_REQUIRED",),
    )
    expected = case.runner._persist(case.plan, evidence)
    select = case.runner._plan_facts
    selected_snapshots = []

    def observed(plan, snapshot, **kwargs):
        selected_snapshots.append(snapshot.manifest_digest)
        return select(plan, snapshot, **kwargs)

    monkeypatch.setattr(case.runner, "_plan_facts", observed)
    reused = case.runner._persist(case.plan, evidence, prepared_facts=prepared)
    assert selected_snapshots == [replacement.manifest_digest]
    assert reused.artifact == expected.artifact and not reused.wrote


@pytest.mark.parametrize("failure", ("missing", "corrupt"))
def test_new_preparation_rechecks_facts_after_prior_stage_succeeded(
    plan_facts_case, failure
):
    case = plan_facts_case
    prepared = case.runner._prepare_plan_facts(case.plan, case.snapshot)
    selected_id = prepared.facts[0].fact_id
    case.change_payload(
        selected_id, None if failure == "missing" else {"fact_id": selected_id}
    )
    with pytest.raises(SnapshotError) as error:
        case.runner._prepare_plan_facts(case.plan, case.snapshot)
    assert error.value.code in {"FACT_NOT_FOUND", "METADATA_CORRUPT"}


@pytest.mark.parametrize("failure", ("missing", "corrupt"))
def test_selected_missing_or_corrupt_fact_is_refused(plan_facts_case, failure):
    case = plan_facts_case
    selected_id = case.retained.canonical_fact_ids[0]
    case.change_payload(
        selected_id, None if failure == "missing" else {"fact_id": selected_id}
    )
    calls = case.state.provider_calls, case.state.parser_calls
    with pytest.raises(SnapshotError) as error:
        case.runner._plan_facts(case.plan, case.snapshot)
    assert error.value.code in {"FACT_NOT_FOUND", "METADATA_CORRUPT"}
    assert calls == (case.state.provider_calls, case.state.parser_calls)


@pytest.mark.parametrize("pin", ("mapping", "source"))
def test_retained_fact_ids_do_not_override_plan_source_and_mapping_pins(
    plan_facts_case, pin
):
    case = plan_facts_case
    selected_id = case.retained.canonical_fact_ids[0]
    payload = case.facts.get(selected_id).model_dump(mode="json")
    if pin == "mapping":
        payload["mapping_decision_id"] = "foreign-mapping"
    else:
        payload["source"]["content_hash"] = "f" * 64
    case.change_payload(selected_id, payload)
    if pin == "source":
        with pytest.raises(SnapshotError):
            case.runner._plan_facts(case.plan, case.snapshot)
        return
    assert selected_id not in {
        fact.fact_id for fact in case.runner._plan_facts(case.plan, case.snapshot)
    }


def test_prepared_stage_reads_each_retained_acquisition_once(
    plan_facts_case, monkeypatch
):
    case = plan_facts_case
    acquisition = case.runner._acquisition
    read = acquisition.retained_acquisition
    requests = []

    def observed(request):
        requests.append(request)
        return read(request)

    monkeypatch.setattr(acquisition, "retained_acquisition", observed)
    prepared = case.runner._prepare_plan_facts(case.plan, case.snapshot)
    assert requests == list(case.plan.ingestions)
    assert {fact.fact_id for fact in prepared.facts} == set(
        case.retained.canonical_fact_ids
    )
    requests.clear()
    assert case.runner._prepare_plan_facts(case.plan, case.snapshot) == prepared
    assert requests == list(case.plan.ingestions)
