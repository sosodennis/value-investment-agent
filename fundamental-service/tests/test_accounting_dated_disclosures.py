from datetime import date
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext

import pytest

from fundamental_service.accounting_roles import (
    AccountingComponentV1,
    AccountingPeriodRuleV1,
    AccountingPeriodV1,
    DatedDisclosureComponentV1,
    DisclosedInstantDateV1,
)
from fundamental_service.arelle_parser import fact_semantic_digest
from fundamental_service.contracts import CanonicalFactV1, QualityStatus
from fundamental_service.facts import (
    canonical_fact_digest,
    verify_accounting_role_evidence,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_accounting_roles import _candidates, _fixture
from test_history_composition import _changed


def _dated_disclosure_fixture(
    *, year=2023, passage_changes=None, numeric_decimals="-6"
):
    snapshot, report, mapping = _fixture()
    period = date(year, 12, 31)
    text = (
        "As of December 31, 2023 and 2022, other receivables from component purchases "
        "were $10.5 billion and $9.2 billion, respectively, in other current assets."
    )
    passage = report.facts[-1].model_copy(
        update={
            "concept": "us-gaap:RevenueFromContractWithCustomerPolicyTextBlock",
            "value": text,
            **(passage_changes or {}),
        }
    )
    numeric = report.facts[0].model_copy(
        update={
            "concept": "us-gaap:AccountsReceivableNetCurrent",
            "instant": period,
            "value": "2000000000",
            "decimals": numeric_decimals,
        }
    )
    token = "10.5" if year == 2023 else "9.2"
    amount_start = text.index(token)
    component = DatedDisclosureComponentV1(
        kind="dated_disclosure",
        parsed_fact_digest=sha256_digest(passage),
        quote_start=0,
        exact_quote=text,
        amount_start=amount_start,
        amount_token=token,
        scale_start=text.index("billion", amount_start),
        scale_token="billion",
        scale=9,
        unit_start=text.index("$", amount_start - 1),
        unit_quote="$",
        reported_unit="iso4217:USD",
        reported_decimals=-8,
        covered_classes=("operating component-purchase receivables",),
        complete_component=True,
        date=DisclosedInstantDateV1(
            period_end=period,
            month_day_start=text.index("December 31"),
            month_day_token="December 31",
            year_start=text.index(str(year)),
            year_token=str(year),
        ),
    )
    rule = AccountingPeriodRuleV1(
        period=AccountingPeriodV1(period_end=period, instant=True),
        disposition="derived",
        components=(
            AccountingComponentV1(parsed_fact_digest=sha256_digest(numeric)),
            component,
        ),
        rationale="Synthetic partial narrative plus numeric operating receivables; no actual semantic review.",
    )
    report = report.model_copy(update={"facts": (numeric, passage)})
    rules = mapping.accounting_rules.model_copy(
        update={
            "normalized_field": "operating_current_receivables",
            "parser_fact_digest": fact_semantic_digest(report),
            "periods": (rule,),
        }
    )
    mapping = mapping.model_copy(
        update={
            "source_concept": "computed:operating_current_receivables",
            "normalized_field": "operating_current_receivables",
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


@pytest.mark.parametrize(
    "year,expected", [(2023, "12500000000"), (2022, "11200000000")]
)
def test_dated_comparative_balance_joins_same_date_numeric_fact_and_retains_sources(
    year, expected
):
    snapshot, report, mapping = _dated_disclosure_fixture(year=year)
    (candidate,) = _candidates(snapshot, report, mapping)
    fact = candidate.canonical_fact(quality=QualityStatus.PROVISIONAL)
    assert fact.value == Decimal(expected)
    assert fact.instant == date(year, 12, 31)
    assert fact.decimals == -8
    assert fact.quality == QualityStatus.PROVISIONAL
    assert set(fact.accounting_evidence.source_facts) == set(report.facts)
    decoded = CanonicalFactV1.model_validate_json(canonical_bytes(fact))
    verify_accounting_role_evidence(decoded, mapping, snapshot)
    assert canonical_fact_digest(decoded) == canonical_fact_digest(fact)
    assert _candidates(snapshot, report, mapping) == (candidate,)
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        assert _candidates(snapshot, report, mapping) == (candidate,)


@pytest.mark.parametrize("decimals,expected", [("-9", -9), ("INF", -8), (None, None)])
def test_dated_aggregation_preserves_coarsest_or_unknown_component_precision(
    decimals, expected
):
    snapshot, report, mapping = _dated_disclosure_fixture(numeric_decimals=decimals)
    (candidate,) = _candidates(snapshot, report, mapping)
    assert candidate.decimals == expected


@pytest.mark.parametrize(
    "changes",
    [
        {"entity_identifier": "0000000002"},
        {"consolidation_scope": "segmented"},
        {"dimensions": (("us-gaap:StatementBusinessSegmentsAxis", "issuer:Segment"),)},
        {"is_numeric": True, "unit": "iso4217:USD"},
        {"period_start": date(2023, 11, 1)},
        {"period_start": date(2024, 1, 1), "period_end": date(2024, 12, 31)},
        {"instant": date(2023, 12, 31)},
        {"value": "A changed passage cannot supply the retained quote."},
    ],
)
def test_dated_disclosure_rejects_wrong_source_scope_period_or_passage(changes):
    snapshot, report, mapping = _dated_disclosure_fixture(passage_changes=changes)
    with pytest.raises(SnapshotError):
        _candidates(snapshot, report, mapping)


@pytest.mark.parametrize(
    "change",
    [
        {"year_token": "2022"},
        {"year_start": 1},
        {"month_day_token": "December 30"},
        {"month_day_start": 0},
        {"period_end": "2022-12-31"},
    ],
)
def test_date_tokens_and_offsets_cannot_be_reassigned(change):
    _, _, mapping = _dated_disclosure_fixture()
    component = mapping.accounting_rules.periods[0].components[-1]
    data = component.model_dump(mode="json")
    data["date"].update(change)
    with pytest.raises(ValueError):
        DatedDisclosureComponentV1.model_validate(data)


@pytest.mark.parametrize(
    "change",
    [
        {"amount_start": 0},
        {"amount_token": "0.5"},
        {"scale": 6},
        {"complete_component": False},
        {"sign": -1},
        {"complete_role": True},
        {"covered_classes": ["receivables", "receivables"]},
    ],
)
def test_dated_components_require_exact_amount_and_partial_role_scope(change):
    _, _, mapping = _dated_disclosure_fixture()
    data = mapping.accounting_rules.periods[0].components[-1].model_dump(mode="json")
    data.update(change)
    with pytest.raises(ValueError):
        DatedDisclosureComponentV1.model_validate(data)


@pytest.mark.parametrize(
    "field,value", [("decimals", -6), ("value", "100"), ("instant", "2022-12-31")]
)
def test_dated_evidence_rechecks_value_date_and_precision_on_canonical_decode(
    field, value
):
    snapshot, report, mapping = _dated_disclosure_fixture()
    (candidate,) = _candidates(snapshot, report, mapping)
    data = candidate.canonical_fact(quality=QualityStatus.PROVISIONAL).model_dump(
        mode="json"
    )
    data[field] = value
    with pytest.raises(ValueError):
        CanonicalFactV1.model_validate(data)


@pytest.mark.parametrize("year", [2022, 2023])
def test_date_cannot_be_assigned_to_a_different_rule_instant(year):
    _, _, mapping = _dated_disclosure_fixture(year=year)
    data = mapping.accounting_rules.periods[0].model_dump(mode="json")
    data["period"]["period_end"] = "2021-12-31"
    with pytest.raises(ValueError, match="same-date instant"):
        AccountingPeriodRuleV1.model_validate(data)


def test_dated_component_cannot_be_counted_twice():
    _, _, mapping = _dated_disclosure_fixture()
    data = mapping.accounting_rules.periods[0].model_dump(mode="json")
    data["components"].append(data["components"][-1])
    with pytest.raises(ValueError, match="repeat a source"):
        AccountingPeriodRuleV1.model_validate(data)


@pytest.mark.parametrize(
    "change",
    [
        {"reported_unit": "iso4217:EUR"},
        {"quote_start": 1},
        {"scale_start": 0},
        {"unit_start": 0},
        {"reported_decimals": -6},
    ],
)
def test_dated_transcription_rechecks_runtime_unit_spans_and_precision(change):
    snapshot, report, mapping = _dated_disclosure_fixture()
    rule = mapping.accounting_rules.periods[0]
    rule = rule.model_copy(
        update={
            "components": (
                rule.components[0],
                rule.components[1].model_copy(update=change),
            )
        }
    )
    mapping = mapping.model_copy(
        update={
            "accounting_rules": mapping.accounting_rules.model_copy(
                update={"periods": (rule,)}
            )
        }
    )
    with pytest.raises(SnapshotError) as error:
        _candidates(snapshot, report, mapping)
    assert error.value.code == "ACCOUNTING_DISCLOSED_AMOUNT_MISMATCH"


def test_dated_component_cannot_escape_the_original_comparative_period():
    snapshot, report, mapping = _dated_disclosure_fixture(
        year=2022,
        passage_changes={
            "period_start": date(2024, 1, 1),
            "period_end": date(2024, 12, 31),
        },
    )
    with pytest.raises(SnapshotError):
        _candidates(snapshot, report, mapping)


def test_same_covered_class_cannot_be_aggregated_from_distinct_passages():
    _, _, mapping = _dated_disclosure_fixture()
    rule = mapping.accounting_rules.periods[0]
    data = rule.model_dump(mode="json")
    duplicate = rule.components[-1].model_dump(mode="json")
    duplicate["parsed_fact_digest"] = "a" * 64
    data["components"].append(duplicate)
    with pytest.raises(ValueError, match="repeat covered classes"):
        AccountingPeriodRuleV1.model_validate(data)
