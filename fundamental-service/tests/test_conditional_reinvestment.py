from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fundamental_service.conditional_reinvestment import (
    ConditionalReinvestmentError,
    assess_conditional_reinvestment,
    bind_conditional_reinvestment_recipe,
    reinvestment_history_requirements_profile,
)
from fundamental_service.conditional_reinvestment_contracts import (
    REINVESTMENT_CORE_FIELDS,
    REINVESTMENT_UNKNOWNS,
    ConditionalReinvestmentRecipeV1,
    ReinvestmentHypothesisV1,
)
from fundamental_service.contracts import (
    CanonicalFactV1,
    QualityStatus,
    SourceSnapshotV1,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.valuation_requirements import valuation_requirements_profile
from test_api import _canonical_fact
from test_postgres_metadata import _snapshot


def _recipe():
    return ConditionalReinvestmentRecipeV1(
        model_id="fcff_dcf",
        model_version="fcff_dcf-v2",
        mapping_version="mapping-v1",
        assumption_document_uri="https://example.test/deployment/forward-hypotheses-v1",
        assumption_document_digest=sha256_digest("retained deployment assumptions"),
        limitations=(
            "These explicit forward assumptions do not reconstruct historical accounting, establish completeness, or claim probabilities or bounds.",
        ),
        scenarios=tuple(
            ReinvestmentHypothesisV1(
                name=name,
                reinvestment_rate=Decimal(rate),
                rationale="Explicit hypothetical forward reinvestment rate for sensitivity; it is not an observed historical rate or a calibrated estimate.",
            )
            for name, rate in (("base", "0.4"), ("downside", "0.6"), ("upside", "0.2"))
        ),
    )


def _with_sources(snapshot, sources):
    payload = snapshot.model_dump(exclude={"manifest_digest"}) | {
        "source_records": tuple(sources),
        "captured_at": max(
            snapshot.captured_at, *(source.captured_at for source in sources)
        ),
    }
    return SourceSnapshotV1.model_validate(
        payload
        | {
            "manifest_digest": sha256_digest(
                {key: value for key, value in payload.items() if key != "snapshot_id"}
            )
        }
    )


def _case(issuer="0000000001"):
    snapshot = _snapshot(
        "forward-reinvestment", valuation_timestamp=datetime(2026, 3, 1, tzinfo=UTC)
    )
    snapshot = snapshot.model_copy(
        update={
            "identity": snapshot.identity.model_copy(
                update={"issuer_id": issuer, "security_id": issuer + "-COMMON"}
            )
        }
    )
    sources, facts = [], []
    for year in (2023, 2024, 2025):
        available = datetime(year + 1, 1, 2, tzinfo=UTC)
        source = snapshot.source_records[0].model_copy(
            update={
                "source_id": "sec-filing",
                "uri": f"https://www.sec.gov/Archives/{issuer}/{year}.htm",
                "accession_number": f"{issuer}-{year % 100:02}-000001",
                "content_hash": sha256_digest((issuer, year)),
                "form": "10-K",
                "available_at": available,
                "filed_at": available,
            }
        )
        sources.append(source)
        for index, field in enumerate(REINVESTMENT_CORE_FIELDS):
            payload = _canonical_fact(f"{field}-{year}", field).model_dump()
            payload.update(
                issuer_id=issuer,
                security_id=snapshot.identity.security_id,
                period_start=date(year, 1, 1),
                period_end=date(year, 12, 31),
                available_at=available,
                filed_at=available,
                accession_number=source.accession_number,
                mapping_decision_id=f"mapping-{field}-{year}",
                value=Decimal((index + 1) * year),
            )
            payload["context"].update(
                entity_scope=issuer,
                unit_qname="iso4217:USD",
                start_date=payload["period_start"],
                end_date=payload["period_end"],
            )
            payload["source"].update(
                source_url=source.uri,
                content_hash=source.content_hash,
                accession_number=source.accession_number,
                available_at=available,
                filed_at=available,
            )
            facts.append(CanonicalFactV1.model_validate(payload))
    return _recipe(), tuple(facts), _with_sources(snapshot, sources)


def _bind(recipe, facts, snapshot):
    return bind_conditional_reinvestment_recipe(recipe, facts, snapshot=snapshot)


def _assess(policy, facts, snapshot, mapping_version="mapping-v1"):
    return assess_conditional_reinvestment(
        policy, facts, snapshot=snapshot, mapping_version=mapping_version
    )


@pytest.mark.parametrize("issuer", ("0000000001", "0000000002"))
def test_same_policy_binds_multiple_issuers_without_changing_observations(issuer):
    recipe, facts, snapshot = _case(issuer)
    before = canonical_bytes(facts)
    first = _bind(recipe, facts, snapshot)
    repeated = _bind(recipe, tuple(reversed(facts)), snapshot)
    assert first.output_digest == repeated.output_digest
    assert first.input_digest == repeated.input_digest
    assert first.fiscal_years == (2023, 2024, 2025)
    assert first.policy.issuer_id == issuer
    assert first.policy.unknowns == REINVESTMENT_UNKNOWNS
    assert first.supported_history_threshold is None
    assert first.status == "provisional_conditional_hypotheses"
    assert canonical_bytes(facts) == before
    assert {fact.normalized_field for fact in first.source_facts} == set(
        REINVESTMENT_CORE_FIELDS
    )
    assert _assess(first.policy, facts, snapshot) == first


def test_new_history_profile_does_not_replace_released_requirements():
    profile = reinvestment_history_requirements_profile("fcff_dcf")
    assert profile.supported_history_threshold is None
    assert profile.candidate_minimum_complete_years == 3
    assert profile.annual_instant_fields == ()
    assert (
        "capital_expenditure"
        in valuation_requirements_profile("fcff_dcf").annual_duration_fields
    )
    with pytest.raises(ConditionalReinvestmentError, match="unsupported forward model"):
        reinvestment_history_requirements_profile("bank_excess_return")


@pytest.mark.parametrize("missing_year", (2023, 2024, 2025))
def test_missing_core_year_is_not_replaced_by_assumptions(missing_year):
    recipe, facts, snapshot = _case()
    facts = tuple(fact for fact in facts if fact.period_end.year != missing_year)
    with pytest.raises(ConditionalReinvestmentError) as caught:
        _bind(recipe, facts, snapshot)
    assert caught.value.code == "CONDITIONAL_REINVESTMENT_HISTORY_INCOMPLETE"


@pytest.mark.parametrize(
    "updates",
    (
        {"issuer_id": "0000000009"},
        {"security_id": "foreign-security"},
        {"mapping_decision_id": None},
        {"quality": QualityStatus.PROVISIONAL},
        {"is_amendment": True, "amendment_scope": "valuation_relevant"},
        {"unit": "shares"},
        {"currency": "EUR"},
        {"accession_number": "other-original"},
        {"period_end": date(2026, 12, 31)},
    ),
)
def test_invalid_core_candidate_cannot_be_silently_dropped(updates):
    recipe, facts, snapshot = _case()
    facts = (facts[0].model_copy(update=updates), *facts[1:])
    with pytest.raises(ConditionalReinvestmentError) as caught:
        _bind(recipe, facts, snapshot)
    assert caught.value.code == "CONDITIONAL_REINVESTMENT_SOURCE_INVALID"


@pytest.mark.parametrize(
    "updates",
    (
        {"content_hash": "0" * 64},
        {"source_url": "https://example.test/unbound"},
        {"accession_number": "other-original"},
        {"available_at": datetime(2026, 4, 1, tzinfo=UTC)},
    ),
)
def test_provenance_must_match_the_retained_original(updates):
    recipe, facts, snapshot = _case()
    fact = facts[0].model_copy(
        update={"source": facts[0].source.model_copy(update=updates)}
    )
    with pytest.raises(ConditionalReinvestmentError) as caught:
        _bind(recipe, (fact, *facts[1:]), snapshot)
    assert caught.value.code == "CONDITIONAL_REINVESTMENT_SOURCE_INVALID"


def test_conflicting_or_duplicate_facts_do_not_authorize_a_policy():
    recipe, facts, snapshot = _case()
    with pytest.raises(ConditionalReinvestmentError) as caught:
        _bind(recipe, (*facts, facts[0]), snapshot)
    assert caught.value.code == "CONDITIONAL_REINVESTMENT_FACT_CONFLICT"
    conflict = facts[0].model_copy(update={"fact_id": "conflict", "value": Decimal(7)})
    with pytest.raises(ConditionalReinvestmentError) as caught:
        _bind(recipe, (*facts, conflict), snapshot)
    assert caught.value.code == "HISTORY_FACT_CONFLICT"


def test_selected_core_flows_cannot_mix_originals():
    recipe, facts, snapshot = _case()
    original = snapshot.source_records[-1]
    later = original.model_copy(
        update={
            "content_hash": "f" * 64,
            "uri": original.uri + "-other",
            "accession_number": "0000000001-26-000002",
            "available_at": original.available_at + timedelta(days=1),
            "captured_at": original.captured_at + timedelta(days=1),
        }
    )
    fact = facts[-1].model_copy(
        update={
            "fact_id": "other-original-tax",
            "available_at": later.available_at,
            "captured_at": later.captured_at,
            "accession_number": later.accession_number,
            "source": facts[-1].source.model_copy(
                update={
                    "content_hash": later.content_hash,
                    "source_url": later.uri,
                    "accession_number": later.accession_number,
                    "available_at": later.available_at,
                    "captured_at": later.captured_at,
                }
            ),
        }
    )
    snapshot = _with_sources(snapshot, (*snapshot.source_records, later))
    with pytest.raises(ConditionalReinvestmentError) as caught:
        _bind(recipe, (*facts, fact), snapshot)
    assert caught.value.code == "CONDITIONAL_REINVESTMENT_ORIGINAL_MISMATCH"


def test_policy_cannot_select_away_changed_observations():
    recipe, facts, snapshot = _case()
    report = _bind(recipe, facts, snapshot)
    changed = facts[-1].model_copy(update={"value": facts[-1].value + Decimal(1)})
    with pytest.raises(ConditionalReinvestmentError) as caught:
        _assess(report.policy, (*facts[:-1], changed), snapshot)
    assert caught.value.code == "CONDITIONAL_REINVESTMENT_OBSERVATIONS_MISMATCH"


def test_bound_policy_cannot_ignore_a_newer_eligible_original():
    recipe, facts, snapshot = _case()
    original = snapshot.source_records[-1]
    later = original.model_copy(
        update={
            "content_hash": "e" * 64,
            "uri": original.uri + "-newer",
            "accession_number": "0000000001-26-000002",
            "available_at": original.available_at + timedelta(days=1),
            "captured_at": original.captured_at + timedelta(days=1),
        }
    )
    snapshot = _with_sources(snapshot, (*snapshot.source_records, later))
    baseline = _bind(recipe, facts, snapshot)
    newer = tuple(
        fact.model_copy(
            update={
                "fact_id": fact.fact_id + "-newer",
                "available_at": later.available_at,
                "captured_at": later.captured_at,
                "accession_number": later.accession_number,
                "source": fact.source.model_copy(
                    update={
                        "content_hash": later.content_hash,
                        "source_url": later.uri,
                        "accession_number": later.accession_number,
                        "available_at": later.available_at,
                        "captured_at": later.captured_at,
                    }
                ),
            }
        )
        for fact in facts[-4:]
    )
    with pytest.raises(ConditionalReinvestmentError) as caught:
        _assess(baseline.policy, (*facts, *newer), snapshot)
    assert caught.value.code == "CONDITIONAL_REINVESTMENT_OBSERVATIONS_MISMATCH"
    rebound = _bind(recipe, (*facts, *newer), snapshot)
    assert {fact.fact_id for fact in newer} <= {
        ref.fact_id for ref in rebound.policy.observations
    }


@pytest.mark.parametrize(
    "updates",
    (
        {"entity_scope": "0000000009"},
        {"unit_qname": "xbrli:shares"},
        {"start_date": date(2023, 2, 1)},
        {"consolidation_scope": "segment"},
        {"concept_qname": "us-gaap:OtherConcept"},
    ),
)
def test_context_must_match_the_observed_period_currency_and_identity(updates):
    recipe, facts, snapshot = _case()
    fact = facts[0].model_copy(
        update={"context": facts[0].context.model_copy(update=updates)}
    )
    with pytest.raises(ConditionalReinvestmentError) as caught:
        _bind(recipe, (fact, *facts[1:]), snapshot)
    assert caught.value.code == "CONDITIONAL_REINVESTMENT_SOURCE_INVALID"


def test_nonannual_core_candidate_is_refused_alongside_complete_history():
    recipe, facts, snapshot = _case()
    assert _bind(recipe, facts, snapshot).fiscal_years == (2023, 2024, 2025)
    quarter = facts[0].model_copy(
        update={
            "fact_id": "quarterly-core-flow",
            "period_start": date(2023, 10, 1),
            "context": facts[0].context.model_copy(
                update={"start_date": date(2023, 10, 1)}
            ),
        }
    )
    with pytest.raises(ConditionalReinvestmentError) as caught:
        _bind(recipe, (*facts, quarter), snapshot)
    assert caught.value.code == "CONDITIONAL_REINVESTMENT_SOURCE_INVALID"


def test_original_cannot_be_available_before_period_end():
    recipe, facts, snapshot = _case()
    assert _bind(recipe, facts, snapshot).fiscal_years == (2023, 2024, 2025)
    sources = {
        source.content_hash: source.model_copy(
            update={"available_at": datetime(2023 + index, 12, 30, tzinfo=UTC)}
        )
        for index, source in enumerate(snapshot.source_records)
    }
    early = tuple(
        fact.model_copy(
            update={
                "available_at": sources[fact.source.content_hash].available_at,
                "source": fact.source.model_copy(
                    update={
                        "available_at": sources[fact.source.content_hash].available_at
                    }
                ),
            }
        )
        for fact in facts
    )
    snapshot = _with_sources(snapshot, sources.values())
    with pytest.raises(ConditionalReinvestmentError) as caught:
        _bind(recipe, early, snapshot)
    assert caught.value.code == "CONDITIONAL_REINVESTMENT_SOURCE_INVALID"


def test_failed_original_http_receipt_is_refused():
    recipe, facts, snapshot = _case()
    assert _bind(recipe, facts, snapshot).fiscal_years == (2023, 2024, 2025)
    source = snapshot.source_records[0].model_copy(update={"http_status": 403})
    snapshot = _with_sources(snapshot, (source, *snapshot.source_records[1:]))
    with pytest.raises(ConditionalReinvestmentError) as caught:
        _bind(recipe, facts, snapshot)
    assert caught.value.code == "CONDITIONAL_REINVESTMENT_SOURCE_INVALID"


@pytest.mark.parametrize(
    "field,code",
    (
        ("policy_digest", "POLICY"),
        ("requirements_digest", "REQUIREMENTS"),
        ("snapshot_manifest_digest", "SNAPSHOT"),
    ),
)
def test_exact_policy_pins_cannot_be_substituted(field, code):
    recipe, facts, snapshot = _case()
    report = _bind(recipe, facts, snapshot)
    with pytest.raises(ConditionalReinvestmentError) as caught:
        _assess(report.policy.model_copy(update={field: "0" * 64}), facts, snapshot)
    assert caught.value.code == f"CONDITIONAL_REINVESTMENT_{code}_MISMATCH"
    with pytest.raises(ConditionalReinvestmentError) as caught:
        _assess(report.policy, facts, snapshot, mapping_version="mapping-v2")
    assert caught.value.code == "CONDITIONAL_REINVESTMENT_MAPPING_MISMATCH"


@pytest.mark.parametrize(
    "updates",
    (
        {"model_version": "fcff_dcf-v1"},
        {"historical_reinvestment_observed": True},
        {"interpretation": "observed_history"},
        {"limitations": (" " * 50,)},
        {"assumption_document_digest": "invalid"},
    ),
)
def test_assumptions_cannot_claim_observed_history_or_an_invalid_version(updates):
    recipe = _recipe()
    with pytest.raises(ValidationError):
        ConditionalReinvestmentRecipeV1.model_validate(recipe.model_dump() | updates)


def test_sensitivity_requires_explicit_distinct_scenarios_and_rates():
    recipe = _recipe()
    for scenarios in (
        (recipe.scenarios[0],) * 3,
        tuple(
            item.model_copy(update={"reinvestment_rate": Decimal("0.4")})
            for item in recipe.scenarios
        ),
    ):
        with pytest.raises(ValidationError):
            ConditionalReinvestmentRecipeV1.model_validate(
                recipe.model_dump() | {"scenarios": scenarios}
            )
    for rate in ("NaN", "Infinity", "1.01", "-1.01"):
        with pytest.raises(ValidationError):
            ReinvestmentHypothesisV1.model_validate(
                recipe.scenarios[0].model_dump() | {"reinvestment_rate": Decimal(rate)}
            )
