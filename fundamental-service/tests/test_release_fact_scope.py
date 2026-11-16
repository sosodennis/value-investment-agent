"""Released fact selection is isolated from unpublished catalog contents."""

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from fundamental_service.contracts import (
    FactsReadRequestV1,
    FiscalPeriodSelectorV1,
    ValuationEvidenceReadRequestV1,
)
from fundamental_service.metadata import (
    PostgresCanonicalFactRepository,
    PostgresMetadataStore,
)
from fundamental_service.operations import ServiceError
from fundamental_service.replay import CacheLifecycle
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import SnapshotError
from test_preparation_runner import _fixture


@pytest.fixture(params=("filesystem", "postgres"))
def release_facts_case(tmp_path, request):
    fixture = _fixture(tmp_path)
    metadata = None
    facts = fixture.facts
    if request.param == "postgres":
        database, _ = request.getfixturevalue("recovery_databases")
        metadata = PostgresMetadataStore(database, auto_migrate=True)
        metadata.start()
        facts = PostgresCanonicalFactRepository(metadata)
        for fact in fixture.facts.list():
            facts.publish(fact)
        fixture.application = replace(fixture.application, fact_repository=facts)

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
                    await connection.execute(
                        text(
                            "DELETE FROM fundamental.canonical_facts WHERE fact_id=:id"
                            if payload is None
                            else "UPDATE fundamental.canonical_facts "
                            "SET payload=CAST(:payload AS jsonb) WHERE fact_id=:id"
                        ),
                        {"id": fact_id, "payload": json.dumps(payload)},
                    )

            metadata._runner.run(mutate())

    def read(operation):
        resolution = fixture.plan.resolution_request().model_copy(
            update={"required_fields": ("revenue",)}
        )
        if operation == "fiscal":
            resolution = resolution.model_copy(
                update={
                    "fiscal_period_selector": FiscalPeriodSelectorV1(
                        mode="latest_complete", count=3
                    )
                }
            )
        if operation in {"default", "fiscal"}:
            return fixture.application.resolve_snapshot(resolution)
        if operation == "facts":
            return fixture.application.read_facts(
                FactsReadRequestV1(
                    contract_version="fundamental.v1",
                    snapshot_id=fixture.snapshot.snapshot_id,
                    data_release_manifest_digest=fixture.manifest.manifest_digest,
                    required_fields=("revenue",),
                )
            )
        assert operation == "valuation"
        return fixture.application.read_valuation_evidence(
            ValuationEvidenceReadRequestV1(
                contract_version="fundamental.v1",
                snapshot_id=fixture.snapshot.snapshot_id,
                data_release_manifest_digest=fixture.manifest.manifest_digest,
                model_id=fixture.plan.model_id,
            )
        )

    try:
        yield SimpleNamespace(
            fixture=fixture,
            facts=facts,
            store=request.param,
            change_payload=change_payload,
            read=read,
        )
    finally:
        if metadata is not None:
            metadata.close()


@pytest.mark.parametrize("operation", ("default", "fiscal", "facts", "valuation"))
def test_unreleased_later_and_corrupt_facts_do_not_change_release(
    release_facts_case, operation
):
    case = release_facts_case
    expected = case.read(operation)
    released = next(
        fact
        for fact in case.facts.list()
        if fact.normalized_field == "revenue" and fact.period_end.year == 2025
    )
    decoy = released.model_copy(
        update={
            "fact_id": "unreleased-revenue",
            "available_at": released.available_at + timedelta(days=1),
            "filed_at": released.filed_at + timedelta(days=1),
            "value": released.value + Decimal("1"),
        }
    )
    case.facts.publish(decoy)
    case.fixture.application = replace(
        case.fixture.application, release_cache=CacheLifecycle()
    )
    assert case.read(operation) == expected
    case.change_payload(decoy.fact_id, {"fact_id": decoy.fact_id})
    case.fixture.application = replace(
        case.fixture.application, release_cache=CacheLifecycle()
    )
    assert case.read(operation) == expected


@pytest.mark.parametrize("operation", ("default", "fiscal", "facts", "valuation"))
@pytest.mark.parametrize("damage", ("missing", "corrupt", "changed"))
def test_declared_fact_damage_is_refused_including_after_cache_hit(
    release_facts_case, operation, damage
):
    case = release_facts_case
    expected = case.read(operation)
    assert case.read(operation) == expected
    selected_id = case.fixture.manifest.snapshot_refs[0].facts[0].fact_id
    payload = None
    if damage == "corrupt":
        payload = {"fact_id": selected_id}
    elif damage == "changed":
        fact = case.facts.get(selected_id)
        payload = fact.model_copy(update={"value": fact.value + Decimal("1")})
        payload = payload.model_dump(mode="json")
    case.change_payload(selected_id, payload)

    with pytest.raises(ServiceError) as error:
        case.read(operation)

    expected_code = (
        "DATA_RELEASE_FACT_MISMATCH"
        if damage == "changed"
        else "METADATA_CORRUPT"
        if damage == "corrupt" and case.store == "postgres"
        else "FACT_NOT_FOUND"
    )
    assert error.value.code == expected_code


@pytest.mark.parametrize("operation", ("default", "fiscal", "facts", "valuation"))
def test_temporary_release_fact_failure_preserves_retryability(
    release_facts_case, operation, monkeypatch
):
    case = release_facts_case
    expected = case.read(operation)
    assert case.read(operation) == expected

    def unavailable(_fact_id):
        raise SnapshotError(
            "METADATA_NOT_READY", "metadata is temporarily unavailable", retryable=True
        )

    monkeypatch.setattr(case.facts, "get", unavailable)

    with pytest.raises(ServiceError) as error:
        case.read(operation)

    assert error.value.code == "METADATA_NOT_READY"
    assert error.value.status_code == 503
    assert error.value.retryable is True
