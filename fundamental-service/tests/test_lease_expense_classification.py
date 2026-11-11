"""Synthetic normalization boundaries; no real issuer mapping approval."""

from datetime import date
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext

import pytest

from fundamental_service.accounting_roles import (
    AccountingComponentV1,
    AccountingPeriodRuleV1,
    AccountingPeriodV1,
    IssuerAccountingRoleRuleSetV1,
)
from fundamental_service.arelle_parser import fact_semantic_digest
from fundamental_service.contracts import CanonicalFactV1, QualityStatus
from fundamental_service.facts import (
    canonical_fact_digest,
    verify_accounting_role_evidence,
)
from fundamental_service.original_issuer import OriginalOperatingSourceV1
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_accounting_roles import _candidates, _fixture
from test_history_composition import _changed


def fixture(*, operating=False, amortization_changes=None, interest_changes=None):
    snapshot, report, mapping = _fixture()
    template = report.facts[0].model_copy(
        update={
            "instant": None,
            "period_start": date(2023, 1, 1),
            "period_end": date(2023, 12, 31),
            "decimals": "-3",
        }
    )
    total = template.model_copy(
        update={"concept": "us-gaap:LeaseCost", "context_id": "total", "value": "10000"}
    )
    observations = tuple(
        template.model_copy(
            update={
                "concept": concept,
                "context_id": location,
                "value": amount,
                "dimensions": (("us-gaap:IncomeStatementLocationAxis", member),),
                "consolidation_scope": "segmented",
                "security_scope": "segmented",
                **(changes or {}),
            }
        )
        for concept, location, member, amount, changes in (
            (
                "us-gaap:FinanceLeaseRightOfUseAssetAmortization",
                "operating_expenses",
                "us-gaap:OperatingExpenseMember",
                "100",
                amortization_changes,
            ),
            (
                "us-gaap:FinanceLeaseInterestExpense",
                "interest_expense",
                "us-gaap:InterestExpenseMember",
                "20",
                interest_changes,
            ),
        )
    )
    components = tuple(
        AccountingComponentV1(
            parsed_fact_digest=sha256_digest(fact),
            sign=-1 if operating else 1,
            finance_lease_expense_location=location,
        )
        for fact, location in zip(
            observations, ("operating_expenses", "interest_expense"), strict=True
        )
    )
    role = "operating_lease_cost" if operating else "finance_lease_cost"
    rule = AccountingPeriodRuleV1(
        period=AccountingPeriodV1(
            period_start=date(2023, 1, 1), period_end=date(2023, 12, 31)
        ),
        disposition="derived",
        components=(AccountingComponentV1(parsed_fact_digest=sha256_digest(total)),)
        + components
        if operating
        else components,
        rationale="Synthetic paired expense classification; not an actual financial review.",
    )
    report = report.model_copy(update={"facts": (total, *observations)})
    rules = mapping.accounting_rules.model_copy(
        update={
            "normalized_field": role,
            "periods": (rule,),
            "parser_fact_digest": fact_semantic_digest(report),
        }
    )
    mapping = mapping.model_copy(
        update={
            "source_concept": f"computed:{role}",
            "normalized_field": role,
            "accounting_rules": rules,
        }
    )
    snapshot = _changed(
        snapshot,
        sec_integrity_evidence=snapshot.sec_integrity_evidence.model_copy(
            update={
                "normalized_fact_digest": fact_semantic_digest(report),
                "archive_fact_digest": fact_semantic_digest(report),
            }
        ),
    )
    return snapshot, report, mapping


@pytest.mark.parametrize("operating,expected", [(False, "120"), (True, "9880")])
def test_expense_classification_retains_dimensions_and_source_bound_value(
    operating, expected
):
    snapshot, report, mapping = fixture(operating=operating)
    (candidate,) = _candidates(snapshot, report, mapping)
    fact = candidate.canonical_fact(quality=QualityStatus.PROVISIONAL)
    assert fact.value == Decimal(expected)
    assert fact.decimals == -3
    assert fact.quality is QualityStatus.PROVISIONAL
    assert not fact.context.dimensions
    assert sum(bool(f.dimensions) for f in fact.accounting_evidence.source_facts) == 2
    decoded = CanonicalFactV1.model_validate_json(canonical_bytes(fact))
    verify_accounting_role_evidence(decoded, mapping, snapshot)
    assert canonical_fact_digest(decoded) == canonical_fact_digest(fact)
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        assert _candidates(snapshot, report, mapping) == (candidate,)


@pytest.mark.parametrize(
    "changes",
    [
        {"concept": "us-gaap:OperatingLeaseCost"},
        {"entity_identifier": "0000000002"},
        {"period_start": date(2022, 1, 1)},
        {"period_end": date(2022, 12, 31)},
        {"unit": "shares"},
        {"consolidation_scope": "consolidated"},
        {"security_scope": "security"},
        {"dimensions": ()},
        {"dimensions": (("srt:RangeAxis", "srt:MaximumMember"),)},
        {
            "dimensions": (
                (
                    "us-gaap:IncomeStatementLocationAxis",
                    "us-gaap:InterestExpenseMember",
                ),
            )
        },
        {
            "dimensions": (
                (
                    "us-gaap:IncomeStatementLocationAxis",
                    "example:OperatingExpenseMember",
                ),
            )
        },
        {
            "dimensions": (
                (
                    "us-gaap:IncomeStatementLocationAxis",
                    "us-gaap:OperatingExpenseMember",
                ),
                ("us-gaap:StatementBusinessSegmentsAxis", "example:Segment"),
            )
        },
        {"value": "-1"},
        {"value": "NaN"},
    ],
)
def test_wrong_finance_expense_source_refuses_without_normalizing_scope(changes):
    snapshot, report, mapping = fixture(amortization_changes=changes)
    with pytest.raises(SnapshotError):
        _candidates(snapshot, report, mapping)


def test_issuer_expense_classification_preserves_original_segmented_observations():
    snapshot, report, mapping = fixture()
    primary = snapshot.source_records[0]
    source = OriginalOperatingSourceV1(
        cik=snapshot.identity.issuer_id,
        accession_number=primary.accession_number,
        uri=primary.uri,
        content_hash=primary.content_hash,
        parser_input_hash=primary.parser_input_hash,
        form=primary.form,
        available_at=primary.available_at,
        captured_at=primary.captured_at,
    )
    rules = IssuerAccountingRoleRuleSetV1.model_validate(
        {
            **mapping.accounting_rules.model_dump(exclude={"protocol", "security_id"}),
            "security_id": None,
        }
    )
    mapping = mapping.model_copy(update={"accounting_rules": rules})
    (candidate,) = parsed_facts_to_candidates(
        report,
        source=source,
        issuer_id=source.cik,
        normalized_field=mapping.normalized_field,
        mapping=mapping,
    )
    fact = candidate.canonical_fact(quality=QualityStatus.PROVISIONAL)
    assert fact.value == Decimal("120")
    assert fact.security_id is None and fact.security_scope == "issuer"
    assert all(
        observation.dimensions
        and observation.consolidation_scope == "segmented"
        and observation.security_scope == "segmented"
        for observation in fact.accounting_evidence.source_facts
    )
    assert CanonicalFactV1.model_validate_json(canonical_bytes(fact)) == fact


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "wrong_sign",
        "wrong_role",
        "wrong_location",
        "wrong_total",
        "extra",
        "unclassified",
        "overlap",
        "exceeds_total",
    ],
)
def test_partial_or_misclassified_expense_groups_refuse(change):
    snapshot, report, mapping = fixture(operating=True)
    rules = mapping.accounting_rules
    rule = rules.periods[0]
    components = list(rule.components)
    role = mapping.normalized_field
    if change == "missing":
        components.pop()
    elif change == "wrong_sign":
        components[1] = components[1].model_copy(update={"sign": 1})
    elif change == "wrong_role":
        role = "depreciation_and_amortization"
    elif change == "wrong_location":
        components[1] = components[1].model_copy(
            update={"finance_lease_expense_location": "interest_expense"}
        )
    elif change == "wrong_total":
        components[0] = components[0].model_copy(update={"sign": -1})
    elif change == "extra":
        components.append(components[0])
    elif change == "unclassified":
        components[1] = components[1].model_copy(
            update={"finance_lease_expense_location": None}
        )
    elif change == "overlap":
        components[2] = components[1]
    else:
        snapshot, report, mapping = fixture(
            operating=True, amortization_changes={"value": "10001"}
        )
        with pytest.raises(SnapshotError) as error:
            _candidates(snapshot, report, mapping)
        assert error.value.code == "ACCOUNTING_LEASE_COST_INVALID"
        return
    raw = mapping.model_dump(mode="json")
    raw.update(source_concept=f"computed:{role}", normalized_field=role)
    raw["accounting_rules"].update(normalized_field=role)
    raw["accounting_rules"]["periods"][0]["components"] = [
        c.model_dump(mode="json") for c in components
    ]
    with pytest.raises((SnapshotError, ValueError)):
        from fundamental_service.facts import CanonicalMappingV1

        altered = CanonicalMappingV1.model_validate(raw)
        _candidates(snapshot, report, altered)


@pytest.mark.parametrize("decimals,expected", [(None, None), ("-6", -6), ("INF", -3)])
def test_expense_precision_preserves_coarsest_or_unknown_observation(
    decimals, expected
):
    snapshot, report, mapping = fixture(interest_changes={"decimals": decimals})
    (candidate,) = _candidates(snapshot, report, mapping)
    assert candidate.decimals == expected


def test_old_component_bytes_omit_the_new_scope_and_mixed_scopes_refuse():
    component = AccountingComponentV1(parsed_fact_digest="a" * 64)
    assert (
        canonical_bytes(component)
        == b'{"parsed_fact_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","sign":1}'
    )
    with pytest.raises(ValueError, match="mix"):
        AccountingComponentV1(
            parsed_fact_digest="a" * 64,
            balance_sheet_location="other_current_liabilities",
            finance_lease_expense_location="operating_expenses",
        )


def test_tampered_expense_result_and_missing_classification_fail_canonical_decode():
    snapshot, report, mapping = fixture()
    (candidate,) = _candidates(snapshot, report, mapping)
    fact = candidate.canonical_fact(quality=QualityStatus.PROVISIONAL)
    payload = fact.model_dump(mode="json")
    payload["value"] = "999"
    with pytest.raises(ValueError):
        CanonicalFactV1.model_validate(payload)
    payload = fact.model_dump(mode="json")
    payload["accounting_evidence"]["period_rule"]["components"][0].pop(
        "finance_lease_expense_location"
    )
    with pytest.raises(ValueError):
        CanonicalFactV1.model_validate(payload)
