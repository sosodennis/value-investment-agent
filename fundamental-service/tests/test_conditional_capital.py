from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fundamental_service.conditional_capital import (
    CAPITAL_UNKNOWNS,
    OBSERVED_CAPITAL_FIELDS,
    CapitalHypothesisV1,
    CapitalObservationRefV1,
    ConditionalCapitalError,
    ConditionalCapitalPolicyV1,
    HypotheticalConvertibleDebtV1,
    HypotheticalConversionV1,
    assess_conditional_capital,
)
from fundamental_service.contracts import (
    CanonicalFactV1,
    PeriodType,
    SourceSnapshotV1,
)
from fundamental_service.facts import canonical_fact_digest
from fundamental_service.accounting_roles import (
    AccountingComponentV1,
    AccountingPeriodRuleV1,
    AccountingPeriodV1,
    AccountingRoleEvidenceV1,
    AccountingRoleRuleSetV1,
)
from fundamental_service.arelle_parser import ParsedXbrlFactV1
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_api import _canonical_fact
from test_postgres_metadata import _snapshot


def _case():
    snapshot = _snapshot(
        "conditional-capital", valuation_timestamp=datetime(2026, 3, 1, tzinfo=UTC)
    )
    source = snapshot.source_records[0].model_copy(
        update={"source_id": "sec-filing", "accession_number": "0000000001-25-000001"}
    )
    payload = snapshot.model_dump(exclude={"manifest_digest"})
    payload["source_records"] = (source,)
    snapshot = SourceSnapshotV1.model_validate(
        {
            **payload,
            "manifest_digest": sha256_digest(
                {key: value for key, value in payload.items() if key != "snapshot_id"}
            ),
        }
    )
    facts = []
    for field in (*OBSERVED_CAPITAL_FIELDS, "equity_award_quantity"):
        fact = _canonical_fact(field, field)
        shares = field in {"common_shares_outstanding", "equity_award_quantity"}
        data = fact.model_dump()
        data.update(
            issuer_id=snapshot.identity.issuer_id,
            security_id=snapshot.identity.security_id,
            value=Decimal("100") if shares else Decimal("1"),
            unit="shares" if shares else "USD",
            currency=None if shares else "USD",
            instant=date(2025, 12, 31),
            period_start=None,
            available_at=source.available_at,
            filed_at=source.available_at,
            mapping_decision_id="mapping-" + field,
        )
        data["concept"] = f"us-gaap:{field}"
        data["context"].update(
            concept_qname=data["concept"],
            entity_scope=snapshot.identity.issuer_id,
            unit_qname=data["unit"],
            period_type=PeriodType.INSTANT,
            start_date=None,
            end_date=None,
            instant=data["instant"],
        )
        data["source"].update(
            available_at=source.available_at, filed_at=source.available_at
        )
        facts.append(CanonicalFactV1.model_validate(data))
    observations = {
        fact.normalized_field: CapitalObservationRefV1(
            fact_id=fact.fact_id, fact_digest=canonical_fact_digest(fact)
        )
        for fact in facts
    }
    rationale = {
        field: "Explicit hypothetical stress operand; original evidence does not establish this amount or a finite bound."
        for field in (
            "preferred_claims",
            "convertible_instruments",
            "other_share_classes",
            "award_dilution",
        )
    }
    scenarios = tuple(
        CapitalHypothesisV1(
            name=name,
            preferred_claims=Decimal(index),
            convertible=HypotheticalConvertibleDebtV1(additional_debt=Decimal(index))
            if index != 2
            else HypotheticalConversionV1(
                additional_common_equivalent_shares=Decimal("20")
            ),
            other_common_equivalent_shares=Decimal(index),
            incremental_award_shares=Decimal(index),
            rationale=rationale,
        )
        for index, name in enumerate(("base", "downside", "upside"))
    )
    policy = ConditionalCapitalPolicyV1(
        model_id="fcff_dcf",
        model_version="fcff_dcf-v2",
        mapping_version="mapping-v1",
        snapshot_manifest_digest=snapshot.manifest_digest,
        issuer_id=snapshot.identity.issuer_id,
        security_id=snapshot.identity.security_id,
        currency=snapshot.identity.currency,
        valuation_timestamp=snapshot.valuation_timestamp,
        period_end=date(2025, 12, 31),
        observations={field: observations[field] for field in OBSERVED_CAPITAL_FIELDS},
        supporting_observations=(observations["equity_award_quantity"],),
        unknowns=CAPITAL_UNKNOWNS,
        limitations=(
            "These conditional amounts are hypothetical stresses, not completeness claims, estimates, statistical intervals or verified economic bounds.",
        ),
        scenarios=scenarios,
    )
    return policy, tuple(facts), snapshot


def _assess(policy, facts, snapshot):
    return assess_conditional_capital(
        policy, facts, snapshot=snapshot, mapping_version="mapping-v1"
    )


def test_source_bound_capital_hypotheses_replay_without_rewriting_observations():
    policy, facts, snapshot = _case()
    original = canonical_bytes(facts)
    report = _assess(policy, facts, snapshot)
    repeated = _assess(policy, tuple(reversed(facts)), snapshot)
    assert report.output_digest == repeated.output_digest
    assert canonical_bytes(facts) == original
    assert report.policy.unknowns == CAPITAL_UNKNOWNS
    assert report.policy.complete_capital_claims is False
    assert report.policy.complete_award_inventory is False
    assert report.status == "provisional_conditional_hypotheses"
    assert (
        report.policy.interpretation == "conditional_hypotheses_not_estimates_or_bounds"
    )
    assert len(report.source_facts) == len(facts)
    base, debt, converted = report.scenarios
    assert (base.bridge.debt, base.bridge.diluted_shares) == (
        Decimal("2"),
        Decimal("100"),
    )
    assert (debt.bridge.debt, debt.bridge.diluted_shares) == (
        Decimal("3"),
        Decimal("102"),
    )
    assert (converted.bridge.debt, converted.bridge.diluted_shares) == (
        Decimal("2"),
        Decimal("124"),
    )
    assert all(row.bridge.lease_liabilities == Decimal("2") for row in report.scenarios)
    assert all(row.bridge.cash == Decimal("1") for row in report.scenarios)


@pytest.mark.parametrize(
    "updates",
    (
        {"complete_capital_claims": True},
        {"complete_award_inventory": True},
        {"unknowns": ()},
        {"unknowns": (*CAPITAL_UNKNOWNS[:-1], CAPITAL_UNKNOWNS[0])},
        {"limitations": ("not enough",)},
        {"model_version": "fcff_dcf-v999"},
        {"valuation_timestamp": datetime(2026, 3, 1)},
        {"period_end": date(2027, 1, 1)},
    ),
)
def test_contract_cannot_claim_completeness_or_drop_unknowns(updates):
    policy, _, _ = _case()
    with pytest.raises(ValueError):
        ConditionalCapitalPolicyV1.model_validate({**policy.model_dump(), **updates})


def test_no_sensitivity_is_not_an_acceptable_unknown_to_zero_policy():
    policy, _, _ = _case()
    for field in (
        "preferred_claims",
        "convertible",
        "other_common_equivalent_shares",
        "incremental_award_shares",
    ):
        scenarios = tuple(
            item.model_copy(update={field: getattr(policy.scenarios[0], field)})
            for item in policy.scenarios
        )
        with pytest.raises(ValueError, match="scenario sensitivity"):
            ConditionalCapitalPolicyV1.model_validate(
                {**policy.model_dump(), "scenarios": scenarios}
            )


def test_convertible_debt_and_conversion_cannot_be_counted_together():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        HypotheticalConvertibleDebtV1.model_validate(
            {
                "treatment": "debt",
                "additional_debt": Decimal("10"),
                "additional_common_equivalent_shares": Decimal("20"),
            }
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        HypotheticalConversionV1.model_validate(
            {
                "treatment": "if_converted",
                "additional_debt": Decimal("10"),
                "additional_common_equivalent_shares": Decimal("20"),
            }
        )


@pytest.mark.parametrize("value", ("NaN", "Infinity", "-1"))
def test_invalid_hypothetical_values_are_refused(value):
    policy, _, _ = _case()
    with pytest.raises(ValueError):
        CapitalHypothesisV1.model_validate(
            {**policy.scenarios[0].model_dump(), "preferred_claims": Decimal(value)}
        )


@pytest.mark.parametrize(
    "updates",
    (
        {"currency": "EUR"},
        {"security_id": "OTHER"},
        {"snapshot_manifest_digest": "f" * 64},
        {"valuation_timestamp": datetime(2026, 3, 2, tzinfo=UTC)},
    ),
)
def test_hypotheses_cannot_cross_snapshot_identity_currency_or_date(updates):
    policy, facts, snapshot = _case()
    with pytest.raises(ConditionalCapitalError, match="exact snapshot") as error:
        _assess(policy.model_copy(update=updates), facts, snapshot)
    assert error.value.code == "CONDITIONAL_CAPITAL_SNAPSHOT_MISMATCH"


@pytest.mark.parametrize(
    "mode",
    (
        "missing",
        "modified",
        "duplicate",
        "conflict",
        "future",
        "wrong_unit",
        "wrong_role",
        "unmapped",
        "unbound_source",
        "missing_award",
    ),
)
def test_missing_conflicting_future_and_unbound_observations_refuse(mode):
    policy, facts, snapshot = _case()
    facts = list(facts)
    original = facts[0]
    if mode == "missing":
        facts.pop(0)
    elif mode == "missing_award":
        policy = policy.model_copy(
            update={
                "supporting_observations": (
                    policy.supporting_observations[0].model_copy(
                        update={"fact_id": "other"}
                    ),
                )
            }
        )
    elif mode == "duplicate":
        facts.append(original)
    elif mode == "conflict":
        facts.append(
            original.model_copy(
                update={"fact_id": "conflicting", "value": Decimal("999")}
            )
        )
    else:
        changes = {
            "modified": {"value": Decimal("999")},
            "future": {
                "available_at": snapshot.valuation_timestamp + timedelta(days=1)
            },
            "wrong_unit": {"unit": "EUR", "currency": "EUR"},
            "wrong_role": {"normalized_field": "inventory"},
            "unmapped": {"mapping_decision_id": None},
            "unbound_source": {
                "source": original.source.model_copy(update={"content_hash": "f" * 64})
            },
        }[mode]
        facts[0] = original.model_copy(update=changes)
        if mode != "modified":
            observations = dict(policy.observations)
            observations[original.normalized_field] = CapitalObservationRefV1(
                fact_id=original.fact_id, fact_digest=canonical_fact_digest(facts[0])
            )
            policy = policy.model_copy(update={"observations": observations})
    with pytest.raises(ConditionalCapitalError):
        _assess(policy, facts, snapshot)


def test_released_observed_claim_cannot_be_replaced_by_a_hypothesis():
    policy, facts, snapshot = _case()
    claim = facts[0].model_copy(
        update={
            "fact_id": "preferred",
            "normalized_field": "preferred_claims",
            "value": Decimal("10"),
        }
    )
    with pytest.raises(ConditionalCapitalError) as error:
        _assess(policy, (*facts, claim), snapshot)
    assert error.value.code == "CONDITIONAL_CAPITAL_OBSERVED_CLAIM_CONFLICT"


def test_policy_requires_the_actual_release_mapping_version():
    policy, facts, snapshot = _case()
    with pytest.raises(ConditionalCapitalError) as error:
        assess_conditional_capital(
            policy, facts, snapshot=snapshot, mapping_version="different-version"
        )
    assert error.value.code == "CONDITIONAL_CAPITAL_MAPPING_MISMATCH"


@pytest.mark.parametrize(
    "role", ("cash_and_equivalents", "operating_current_receivables")
)
def test_non_operating_assets_cannot_reuse_cash_or_operating_balance_observations(role):
    policy, facts, snapshot = _case()
    asset = next(
        fact for fact in facts if fact.normalized_field == "non_operating_assets"
    )
    cash = next(
        fact for fact in facts if fact.normalized_field == "cash_and_equivalents"
    )
    observation = (
        cash
        if role == "cash_and_equivalents"
        else cash.model_copy(
            update={
                "fact_id": "operating-observation",
                "normalized_field": role,
                "concept": "us-gaap:Receivables",
                "context": cash.context.model_copy(
                    update={"concept_qname": "us-gaap:Receivables"}
                ),
            }
        )
    )
    overlapping_asset = asset.model_copy(
        update={"concept": observation.concept, "context": observation.context}
    )
    references = dict(policy.observations)
    references["non_operating_assets"] = CapitalObservationRefV1(
        fact_id=asset.fact_id, fact_digest=canonical_fact_digest(overlapping_asset)
    )
    selected = tuple(
        overlapping_asset if fact.fact_id == asset.fact_id else fact for fact in facts
    )
    if role != "cash_and_equivalents":
        selected = (*selected, observation)
    with pytest.raises(ConditionalCapitalError) as error:
        _assess(
            policy.model_copy(update={"observations": references}), selected, snapshot
        )
    assert error.value.code == "NON_OPERATING_ASSET_OVERLAP"


def test_convertible_tag_change_with_zero_exposures_is_not_sensitivity():
    policy, _, _ = _case()
    scenarios = tuple(
        item.model_copy(
            update={
                "convertible": HypotheticalConvertibleDebtV1(additional_debt=Decimal(0))
                if index != 1
                else HypotheticalConversionV1(
                    additional_common_equivalent_shares=Decimal(0)
                )
            }
        )
        for index, item in enumerate(policy.scenarios)
    )
    with pytest.raises(ValueError, match="scenario sensitivity: convertible"):
        ConditionalCapitalPolicyV1.model_validate(
            {**policy.model_dump(), "scenarios": scenarios}
        )


@pytest.mark.parametrize(
    "field,value",
    (
        ("period_start", date(2025, 1, 1)),
        ("period_end", date(2025, 12, 30)),
        ("context.period_type", PeriodType.DURATION),
        ("context.instant", date(2025, 12, 30)),
        ("context.entity_scope", "parent"),
        ("context.concept_qname", "us-gaap:WrongConcept"),
    ),
)
def test_inconsistent_instant_or_context_is_refused(field, value):
    policy, facts, snapshot = _case()
    original = facts[0]
    if field.startswith("context."):
        modified = original.model_copy(
            update={
                "context": original.context.model_copy(
                    update={field.split(".")[1]: value}
                )
            }
        )
    else:
        modified = original.model_copy(update={field: value})
    references = dict(policy.observations)
    references[original.normalized_field] = CapitalObservationRefV1(
        fact_id=original.fact_id, fact_digest=canonical_fact_digest(modified)
    )
    with pytest.raises(ConditionalCapitalError) as error:
        _assess(
            policy.model_copy(update={"observations": references}),
            (modified, *facts[1:]),
            snapshot,
        )
    assert error.value.code == "CONDITIONAL_CAPITAL_OBSERVATION_INVALID"


def test_conditional_computed_assets_share_the_exact_positive_observation_guard():
    policy, facts, snapshot = _case()
    cash = next(
        fact for fact in facts if fact.normalized_field == "cash_and_equivalents"
    )
    asset = next(
        fact for fact in facts if fact.normalized_field == "non_operating_assets"
    )
    observations = tuple(
        ParsedXbrlFactV1(
            concept=concept,
            context_id=concept,
            value=value,
            unit="iso4217:USD",
            entity_identifier=cash.issuer_id,
            instant=cash.instant,
            is_numeric=True,
            consolidation_scope="consolidated",
        )
        for concept, value in (
            ("us-gaap:Investments", "50"),
            (cash.concept, str(cash.value)),
        )
    )
    period_rule = AccountingPeriodRuleV1(
        period=AccountingPeriodV1(period_end=cash.instant, instant=True),
        disposition="derived",
        components=tuple(
            AccountingComponentV1(parsed_fact_digest=sha256_digest(fact), sign=1)
            for fact in observations
        ),
        rationale="Synthetic aggregate investment disclosure with a reused positive cash observation",
    )
    rules = AccountingRoleRuleSetV1(
        policy_version="synthetic-assets-v1",
        normalized_field="non_operating_assets",
        issuer_id=cash.issuer_id,
        security_id=cash.security_id,
        accession_number=cash.accession_number,
        raw_content_hash=cash.source.content_hash,
        parser_input_hash="b" * 64,
        parser_fact_digest=sha256_digest(observations),
        unit="iso4217:USD",
        currency="USD",
        periods=(period_rule,),
    )
    evidence = AccountingRoleEvidenceV1(
        rule_set=rules,
        period_rule=period_rule,
        source_facts=tuple(sorted(observations, key=sha256_digest)),
        value=Decimal(51),
    )
    concept = "computed:non_operating_assets"
    computed = CanonicalFactV1.model_validate(
        {
            **asset.model_dump(),
            "concept": concept,
            "value": evidence.value,
            "unit": "iso4217:USD",
            "accounting_evidence": evidence,
            "context": asset.context.model_copy(
                update={"concept_qname": concept, "unit_qname": "iso4217:USD"}
            ),
        }
    )
    references = dict(policy.observations)
    references["non_operating_assets"] = CapitalObservationRefV1(
        fact_id=computed.fact_id, fact_digest=canonical_fact_digest(computed)
    )
    selected = tuple(
        computed if fact.fact_id == asset.fact_id else fact for fact in facts
    )
    with pytest.raises(ConditionalCapitalError) as error:
        _assess(
            policy.model_copy(update={"observations": references}), selected, snapshot
        )
    assert error.value.code == "NON_OPERATING_ASSET_OVERLAP"


def test_newer_eligible_common_share_observation_cannot_be_ignored():
    policy, facts, snapshot = _case()
    common = next(
        fact for fact in facts if fact.normalized_field == "common_shares_outstanding"
    )
    newer = common.model_copy(
        update={
            "fact_id": "newer-shares",
            "instant": date(2026, 1, 1),
            "period_end": date(2026, 1, 1),
            "value": Decimal("101"),
            "context": common.context.model_copy(update={"instant": date(2026, 1, 1)}),
        }
    )
    with pytest.raises(ConditionalCapitalError) as error:
        _assess(policy, (*facts, newer), snapshot)
    assert error.value.code == "CONDITIONAL_CAPITAL_OBSERVATION_SUPERSEDED"
