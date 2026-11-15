"""The source inventory explains evidence without resolving financial sufficiency."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from fundamental_service.contracts import IdentityV1, QualityStatus
from fundamental_service.data_releases import ArtifactRefV1
from fundamental_service.preparation_runner import SourcePreparationEvidenceV1
from fundamental_service.serialization import canonical_bytes
from fundamental_service.valuation_fact_evidence import (
    SourceFactEvidenceInventoryV1,
    SourceMappingRefusalV1,
    build_source_fact_inventory,
)
from fundamental_service.valuation_requirements import (
    conditional_reinvestment_requirements_profile,
    valuation_requirements_profile,
)
from test_accounting_roles import _candidates, _fixture
from test_postgres_metadata import _snapshot
from test_valuation_preparation import _fact, VALUATION_TIME


def source():
    return _snapshot(
        "inventory",
        identity=IdentityV1(
            issuer_id="0000000001",
            issuer_name="Example Co",
            domicile="US",
            reporting_basis="us-gaap",
            security_id="COMMON",
            share_class="common",
            currency="USD",
        ),
        valuation_timestamp=VALUATION_TIME,
    )


def test_direct_zero_remains_observed_and_missing_supporting_role_remains_unknown():
    profile = conditional_reinvestment_requirements_profile("fcff_dcf")
    fact = _fact("current_interest_bearing_debt", 2025, "0", instant=True)
    inventory = build_source_fact_inventory((fact,), snapshot=source(), profile=profile)
    roles = {row.normalized_field: row for row in inventory.roles}

    assert roles["current_interest_bearing_debt"].observations[0].state == "observed"
    assert roles["depreciation_and_amortization"].state == "unknown"
    assert not roles["depreciation_and_amortization"].required
    assert roles["preferred_claims"].state == "unknown"
    assert roles["preferred_claims"].required
    assert (
        SourceFactEvidenceInventoryV1.model_validate_json(canonical_bytes(inventory))
        == inventory
    )


@pytest.mark.parametrize("disposition", ["derived", "confirmed_absent", "disclosed"])
def test_accounting_disposition_is_preserved_from_validated_original(disposition):
    snapshot, report, mapping = _fixture(disposition=disposition)
    (candidate,) = _candidates(snapshot, report, mapping)
    fact = candidate.canonical_fact(quality=QualityStatus.VERIFIED)
    inventory = build_source_fact_inventory(
        (fact,), snapshot=snapshot, profile=valuation_requirements_profile("fcff_dcf")
    )
    row = next(
        r for r in inventory.roles if r.normalized_field == fact.normalized_field
    )
    assert row.observations[0].state == (
        "observed" if disposition == "disclosed" else disposition
    )


@pytest.mark.parametrize("change", ["future", "source", "quality", "issuer"])
def test_ineligible_candidates_are_retained_without_becoming_observations(change):
    fact = _fact("cash_and_equivalents", 2025, "10", instant=True)
    changes = {
        "future": {"available_at": datetime(2027, 1, 1, tzinfo=UTC)},
        "source": {"source": fact.source.model_copy(update={"content_hash": "f" * 64})},
        "quality": {"quality": QualityStatus.PROVISIONAL},
        "issuer": {"issuer_id": "0000000002"},
    }
    fact = fact.model_copy(update=changes[change])
    inventory = build_source_fact_inventory(
        (fact,), snapshot=source(), profile=valuation_requirements_profile("fcff_dcf")
    )
    row = next(
        r for r in inventory.roles if r.normalized_field == fact.normalized_field
    )
    assert row.state == "unknown" and not row.observations
    assert row.rejected_candidates[0].fact_id == fact.fact_id


def test_conflicting_observations_are_retained_and_input_order_is_irrelevant():
    first = _fact("cash_and_equivalents", 2025, "10", instant=True)
    second = _fact(
        "cash_and_equivalents", 2025, "999", instant=True, fact_id="conflicting-cash"
    )
    kwargs = {
        "snapshot": source(),
        "profile": valuation_requirements_profile("fcff_dcf"),
    }
    inventory = build_source_fact_inventory((first, second), **kwargs)
    repeated = build_source_fact_inventory((second, first, first), **kwargs)
    row = next(
        r for r in inventory.roles if r.normalized_field == first.normalized_field
    )
    assert len(row.observations) == 2
    assert inventory == repeated and inventory.digest == repeated.digest
    assert inventory.scope == "mapped_observations_not_completeness_or_model_readiness"


def test_preparation_report_cannot_attach_inventory_for_another_snapshot():
    snapshot = source()
    inventory = build_source_fact_inventory(
        (), snapshot=snapshot, profile=valuation_requirements_profile("fcff_dcf")
    )
    with pytest.raises(ValidationError, match="exact snapshot"):
        SourcePreparationEvidenceV1(
            source_revision="a" * 40,
            plan_digest="b" * 64,
            status="blocked",
            snapshot_id=snapshot.snapshot_id,
            snapshot_manifest_digest="c" * 64,
            fact_evidence_inventory=inventory,
        )


def refusal(snapshot, *, role="preferred_claims", proposal_index=0, batch="a"):
    original = snapshot.source_records[0]
    return SourceMappingRefusalV1(
        normalized_field=role,
        accession_number=original.accession_number,
        source_content_hash=original.content_hash,
        batch_ref=ArtifactRefV1(
            artifact_id="mapping-batch-" + batch,
            content_hash=batch * 64,
            media_type="application/json",
            role="automatic-mapping-batch-decision-v1",
        ),
        proposal_index=proposal_index,
        reason_codes=("MAPPING_AUTOMATIC_RULE_UNSUPPORTED",),
    )


def mapping_source():
    snapshot = source()
    return snapshot.model_copy(
        update={
            "source_records": (
                snapshot.source_records[0].model_copy(
                    update={"accession_number": "0000000001-26-000001"}
                ),
            )
        }
    )


def test_mapping_refusals_do_not_change_observation_state_and_replay_canonically():
    snapshot = mapping_source()
    fact = _fact("cash_and_equivalents", 2025, "10", instant=True)
    missing = refusal(snapshot)
    observed = refusal(snapshot, role=fact.normalized_field, proposal_index=1)
    older_source = snapshot.source_records[0].model_copy(
        update={"accession_number": "0000000001-24-000001", "content_hash": "b" * 64}
    )
    snapshot = snapshot.model_copy(
        update={"source_records": (*snapshot.source_records, older_source)}
    )
    earlier = missing.model_copy(
        update={
            "accession_number": older_source.accession_number,
            "source_content_hash": older_source.content_hash,
            "batch_ref": missing.batch_ref.model_copy(
                update={"artifact_id": "older-batch", "content_hash": "c" * 64}
            ),
        }
    )
    options = dict(
        snapshot=snapshot, profile=valuation_requirements_profile("fcff_dcf")
    )
    inventory = build_source_fact_inventory(
        (fact,), mapping_refusals=(missing, observed, earlier), **options
    )
    repeat = build_source_fact_inventory(
        (fact,), mapping_refusals=(earlier, missing, observed, missing), **options
    )
    assert inventory == repeat and inventory.digest == repeat.digest
    rows = {row.normalized_field: row for row in inventory.roles}
    assert rows["preferred_claims"].state == "unknown"
    assert {
        canonical_bytes(item) for item in rows["preferred_claims"].mapping_refusals
    } == {
        canonical_bytes(missing),
        canonical_bytes(earlier),
    }
    assert rows[fact.normalized_field].state == "observations_available"
    assert rows[fact.normalized_field].mapping_refusals == (observed,)
    assert rows[fact.normalized_field].observations[0].state == "observed"


@pytest.mark.parametrize("change", ("source", "accession", "future", "role"))
def test_mapping_refusals_require_available_snapshot_originals_and_model_roles(change):
    snapshot = mapping_source()
    diagnostic = refusal(snapshot)
    if change == "future":
        snapshot = snapshot.model_copy(
            update={
                "source_records": tuple(
                    item.model_copy(
                        update={"available_at": datetime(2027, 1, 1, tzinfo=UTC)}
                    )
                    for item in snapshot.source_records
                )
            }
        )
    else:
        diagnostic = diagnostic.model_copy(
            update={
                "source": {"source_content_hash": "f" * 64},
                "accession": {"accession_number": "0000000002-25-000001"},
                "role": {"normalized_field": "invented_model_input"},
            }[change]
        )
    with pytest.raises(ValueError, match="available snapshot sources and roles"):
        build_source_fact_inventory(
            (),
            snapshot=snapshot,
            profile=valuation_requirements_profile("fcff_dcf"),
            mapping_refusals=(diagnostic,),
        )


def test_empty_mapping_diagnostics_do_not_rewrite_retained_inventory_bytes():
    inventory = build_source_fact_inventory(
        (), snapshot=source(), profile=valuation_requirements_profile("fcff_dcf")
    )
    assert b"mapping_refusals" not in canonical_bytes(inventory)
    assert (
        SourceFactEvidenceInventoryV1.model_validate_json(canonical_bytes(inventory))
        == inventory
    )
