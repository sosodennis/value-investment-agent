"""A dated balance in annual prose retains its period and exact source spans."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fundamental_service.accounting_roles import (
    AccountingPeriodRuleV1,
    AccountingPeriodV1,
    AccountingRoleError,
    DisclosedInstantAmountV1,
    DisclosedInstantDateV1,
    evaluate_period_rule,
)
from fundamental_service.arelle_parser import fact_semantic_digest
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_accounting_roles import _candidates, _fixture
from test_history_composition import _changed


TEXT = (
    "There was $4,181 of unrecognized stock-based compensation as of March 31, "
    "2023 related to nonvested options."
)


def instant_fixture(*, text=TEXT, source_changes=None):
    snapshot, report, mapping = _fixture(disposition="disclosed")
    source = report.facts[-1].model_copy(
        update={
            "value": text,
            "period_start": date(2022, 4, 1),
            "period_end": date(2023, 3, 31),
            **(source_changes or {}),
        }
    )
    amount = DisclosedInstantAmountV1(
        parsed_fact_digest=sha256_digest(source),
        quote_start=0,
        exact_quote=text,
        amount_start=text.index("4,181"),
        amount_token="4,181",
        scale_start=text.index("$"),
        scale_token="$",
        scale=0,
        unit_start=text.index("$"),
        unit_quote="$",
        reported_unit="iso4217:USD",
        reported_decimals=0,
        covered_classes=("unrecognized compensation for nonvested options",),
        complete_role=True,
        date=DisclosedInstantDateV1(
            period_end=date(2023, 3, 31),
            month_day_start=text.index("March 31"),
            month_day_token="March 31",
            year_start=text.index("2023"),
            year_token="2023",
        ),
    )
    rule = AccountingPeriodRuleV1(
        period=AccountingPeriodV1(period_end=date(2023, 3, 31), instant=True),
        disposition="disclosed",
        disclosed_amount=amount,
        rationale="Synthetic dated option-cost disclosure, not an inventory approval.",
    )
    report = report.model_copy(update={"facts": (source,)})
    rules = mapping.accounting_rules.model_copy(
        update={
            "normalized_field": "equity_award_unrecognized_compensation",
            "periods": (rule,),
            "parser_fact_digest": fact_semantic_digest(report),
        }
    )
    mapping = mapping.model_copy(
        update={
            "normalized_field": rules.normalized_field,
            "source_concept": "computed:" + rules.normalized_field,
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


def test_single_dated_balance_rebuilds_without_retagging_annual_source():
    snapshot, report, mapping = instant_fixture()
    restored = type(mapping).model_validate_json(canonical_bytes(mapping))
    first = _candidates(snapshot, report, mapping)
    second = _candidates(snapshot, report, restored)
    assert canonical_bytes(first) == canonical_bytes(second)
    assert len(first) == 1
    candidate = first[0]
    assert candidate.value == Decimal(4181)
    assert candidate.instant == date(2023, 3, 31)
    assert candidate.period_start is None and candidate.period_end is None
    assert candidate.decimals == 0
    assert candidate.accounting_evidence.source_facts == report.facts
    assert report.facts[0].instant is None
    assert report.facts[0].period_start == date(2022, 4, 1)
    assert report.facts[0].period_end == date(2023, 3, 31)


@pytest.mark.parametrize(
    "changes",
    [
        {"period_start": date(2023, 3, 1)},
        {"period_end": date(2022, 3, 31)},
        {"period_start": date(2023, 4, 2), "period_end": date(2024, 3, 31)},
        {"instant": date(2023, 3, 31)},
        {"is_numeric": True},
    ],
)
def test_instant_requires_annual_source_covering_the_explicit_date(changes):
    _, report, mapping = instant_fixture(source_changes=changes)
    rules = mapping.accounting_rules
    with pytest.raises(AccountingRoleError):
        evaluate_period_rule(rules, rules.periods[0], report.facts)


@pytest.mark.parametrize("mutation", ["date", "date_offset", "amount", "quote", "unit"])
def test_in_process_forgery_is_rejected_at_evaluation(mutation):
    _, report, mapping = instant_fixture()
    rules = mapping.accounting_rules
    rule = rules.periods[0]
    amount = rule.disclosed_amount
    changes = {
        "date": {
            "date": amount.date.model_copy(update={"period_end": date(2024, 3, 31)})
        },
        "date_offset": {"date": amount.date.model_copy(update={"year_start": 0})},
        "amount": {"amount_token": "4,182"},
        "quote": {"quote_start": 1},
        "unit": {"reported_unit": "iso4217:EUR"},
    }[mutation]
    forged = rule.model_copy(
        update={"disclosed_amount": amount.model_copy(update=changes)}
    )
    with pytest.raises(AccountingRoleError):
        evaluate_period_rule(rules, forged, report.facts)


def test_dated_amount_cannot_be_reused_for_another_period_or_duration():
    _, _, mapping = instant_fixture()
    rule = mapping.accounting_rules.periods[0]
    for period in (
        AccountingPeriodV1(period_end=date(2024, 3, 31), instant=True),
        AccountingPeriodV1(period_start=date(2022, 4, 1), period_end=date(2023, 3, 31)),
    ):
        with pytest.raises(ValidationError, match="date must match"):
            AccountingPeriodRuleV1.model_validate(
                {**rule.model_dump(), "period": period}
            )


def test_existing_duration_disclosure_serialization_has_no_new_fields():
    _, _, mapping = _fixture(disposition="disclosed")
    raw = canonical_bytes(mapping)
    assert b'"date":' not in raw
    assert canonical_bytes(type(mapping).model_validate_json(raw)) == raw
