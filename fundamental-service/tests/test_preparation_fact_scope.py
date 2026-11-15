"""Automatic preparation reads the facts retained by its exact acquisitions."""

import json
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
from fundamental_service.preparation_runner import SourcePreparationRunner
from fundamental_service.serialization import canonical_bytes
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
