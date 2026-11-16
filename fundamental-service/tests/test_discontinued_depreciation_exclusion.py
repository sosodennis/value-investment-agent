"""Synthetic accounting boundaries, without real issuer review or release authority."""

from datetime import date
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext

import pytest
from pydantic import ValidationError

from fundamental_service.accounting_roles import (
    AccountingComponentV1,
    AccountingPeriodRuleV1,
    AccountingPeriodV1,
    DiscontinuedDepreciationExclusionV1,
    DiscontinuedDepreciationPassageV1,
)
from fundamental_service.arelle_parser import fact_semantic_digest
from fundamental_service.contracts import CanonicalFactV1, QualityStatus
from fundamental_service.facts import (
    CanonicalMappingV1,
    verify_accounting_role_evidence,
)
from fundamental_service.original_issuer import (
    compose_issuer_operating_source,
    evaluate_original_issuer,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_issuer_accounting_roles import candidates, issuer_rule
from test_original_issuer import DECISION

DIMENSIONS = (
    (
        "us-gaap:IncomeStatementLocationAxis",
        "example:IncomeLossFromOperationsOfDiscontinuedBusinessNetOfTaxMember",
    ),
    ("us-gaap:StatementBusinessSegmentsAxis", "us-gaap:AllOtherSegmentsMember"),
)
CONCEPT = "us-gaap:DepreciationDepletionAndAmortization"


def fixture(*, base_changes=None, excluded_changes=None, passage_changes=None):
    view, mapping, security = issuer_rule()
    report = view.originals[0].report
    template = next(f for f in report.facts if f.is_numeric)
    base = template.model_copy(
        update={
            "concept": CONCEPT,
            "context_id": "consolidated-duration",
            "value": "46144000",
            "decimals": "-3",
            "instant": None,
            "period_start": date(2023, 1, 1),
            "period_end": date(2023, 12, 31),
            **(base_changes or {}),
        }
    )
    excluded = template.model_copy(
        update={
            "concept": CONCEPT,
            "context_id": "discontinued-duration",
            "value": "5000000",
            "decimals": "-6",
            "instant": None,
            "period_start": date(2023, 1, 1),
            "period_end": date(2023, 12, 31),
            "dimensions": DIMENSIONS,
            "consolidation_scope": "segmented",
            "security_scope": "segmented",
            **(excluded_changes or {}),
        }
    )
    passage = template.model_copy(
        update={
            "concept": "us-gaap:SegmentReportingDisclosureTextBlock",
            "context_id": "comparative-classification",
            "value": "The 2023 total includes depreciation and amortization in income of discontinued business.",
            "is_numeric": False,
            "unit": None,
            "decimals": None,
            "instant": None,
            "period_start": date(2024, 1, 1),
            "period_end": date(2024, 12, 31),
            **(passage_changes or {}),
        }
    )
    exclusion = DiscontinuedDepreciationExclusionV1(
        dimensions=DIMENSIONS,
        consolidated_base_fact_digest=sha256_digest(base),
        classification_passage=DiscontinuedDepreciationPassageV1(
            parsed_fact_digest=sha256_digest(passage), exact_quote=passage.value
        ),
    )
    rule = AccountingPeriodRuleV1(
        period=AccountingPeriodV1(
            period_start=date(2023, 1, 1), period_end=date(2023, 12, 31)
        ),
        disposition="derived",
        components=(
            AccountingComponentV1(parsed_fact_digest=sha256_digest(base)),
            AccountingComponentV1(
                parsed_fact_digest=sha256_digest(excluded),
                sign=-1,
                discontinued_depreciation_exclusion=exclusion,
            ),
        ),
        rationale="Synthetic classification with original rounding retained, unapproved.",
    )
    report = report.model_copy(
        update={"facts": (*report.facts, base, excluded, passage)}
    )
    claim = evaluate_original_issuer(
        report, source=view.originals[0].source, decision_at=DECISION
    )
    view = compose_issuer_operating_source((claim,), valuation_timestamp=DECISION)
    rules = mapping.accounting_rules.model_copy(
        update={
            "normalized_field": "depreciation_and_amortization",
            "periods": (rule,),
            "parser_fact_digest": fact_semantic_digest(report),
        }
    )
    mapping = mapping.model_copy(
        update={
            "source_concept": "computed:depreciation_and_amortization",
            "normalized_field": "depreciation_and_amortization",
            "accounting_rules": rules,
            "status": "provisional",
            "confidence": "unresolved",
        }
    )
    return view, mapping, security


def test_duration_exclusion_retains_original_dimensions_precision_and_provisional_quality():
    view, mapping, security = fixture()
    mapping = CanonicalMappingV1.model_validate_json(canonical_bytes(mapping))
    (candidate,) = candidates(view, mapping)
    fact = candidate.canonical_fact(quality=QualityStatus.PROVISIONAL)
    restored = CanonicalFactV1.model_validate_json(canonical_bytes(fact))
    assert restored == fact and fact.value == Decimal("41144000")
    assert fact.quality == QualityStatus.PROVISIONAL
    assert fact.decimals == -6
    assert mapping.status == "provisional"
    evidence = fact.accounting_evidence
    assert evidence is not None and len(evidence.source_facts) == 3
    excluded = next(f for f in evidence.source_facts if f.dimensions)
    assert excluded.dimensions == DIMENSIONS
    assert excluded.consolidation_scope == "segmented"
    assert excluded.value == "5000000" and excluded.decimals == "-6"
    verify_accounting_role_evidence(restored, mapping, view)
    with pytest.raises(SnapshotError):
        verify_accounting_role_evidence(restored, mapping, security)
    assert candidates(view, mapping) == (candidate,)
    with localcontext() as caller:
        caller.prec = 2
        caller.rounding = ROUND_DOWN
        caller.traps[Inexact] = True
        caller.clear_flags()
        assert candidates(view, mapping) == (candidate,)
        assert caller.prec == 2 and caller.rounding == ROUND_DOWN
        assert not caller.flags[Inexact]


@pytest.mark.parametrize(
    "changes",
    (
        {"dimensions": DIMENSIONS[1:]},
        {"consolidation_scope": "consolidated"},
        {"security_scope": "security"},
        {"entity_identifier": "0000000002"},
        {"period_start": date(2022, 1, 1)},
        {"period_end": date(2022, 12, 31)},
        {"instant": date(2023, 12, 31)},
        {"unit": "iso4217:EUR"},
        {"concept": "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"},
        {"value": "-1"},
        {"value": "50000000"},
        {"value": "NaN"},
        {"value": "Infinity"},
    ),
)
def test_discontinued_component_cannot_escape_scope_period_unit_or_base(changes):
    view, mapping, _ = fixture(excluded_changes=changes)
    with pytest.raises(SnapshotError):
        candidates(view, mapping)


@pytest.mark.parametrize(
    "changes",
    (
        {"concept": "us-gaap:Depreciation"},
        {"value": "4000000"},
        {"value": "-1"},
        {"dimensions": DIMENSIONS, "consolidation_scope": "segmented"},
        {"entity_identifier": "0000000002"},
        {"unit": "iso4217:EUR"},
        {"period_end": date(2022, 12, 31)},
    ),
)
def test_positive_base_must_be_aligned_consolidated_depreciation(changes):
    view, mapping, _ = fixture(base_changes=changes)
    with pytest.raises(SnapshotError):
        candidates(view, mapping)


@pytest.mark.parametrize(
    "changes",
    (
        {
            "value": "The 2023 total includes depreciation and amortization of other segments."
        },
        {
            "value": "The 2022 total includes depreciation and amortization of discontinued business."
        },
        {"concept": "us-gaap:UnrelatedTextBlock"},
        {"period_end": date(2022, 12, 31)},
        {"entity_identifier": "0000000002"},
        {"dimensions": DIMENSIONS, "consolidation_scope": "segmented"},
    ),
)
def test_classification_requires_exact_original_period_and_discontinued_passage(
    changes,
):
    view, mapping, _ = fixture(passage_changes=changes)
    with pytest.raises(SnapshotError):
        candidates(view, mapping)


def test_unscoped_dimensions_and_unrelated_role_remain_unsupported():
    view, mapping, _ = fixture()
    rules = mapping.accounting_rules
    rule = rules.periods[0]
    component = rule.components[1]
    unscoped = component.model_copy(
        update={"discontinued_depreciation_exclusion": None}
    )
    changed_rule = rule.model_copy(
        update={"components": (rule.components[0], unscoped)}
    )
    for changed in (
        rules.model_copy(update={"periods": (changed_rule,)}),
        rules.model_copy(update={"normalized_field": "capital_expenditure"}),
    ):
        with pytest.raises(SnapshotError):
            candidates(view, mapping.model_copy(update={"accounting_rules": changed}))


@pytest.mark.parametrize(
    "dimensions",
    (
        DIMENSIONS[1:],
        tuple(reversed(DIMENSIONS)),
        (DIMENSIONS[0], DIMENSIONS[0]),
        (("us-gaap:IncomeStatementLocationAxis", "example:ContinuingMember"),),
        (DIMENSIONS[0], ("us-gaap:GeographicalAreasAxis", "example:DomesticMember")),
    ),
)
def test_arbitrary_or_ambiguous_dimensional_scopes_cannot_be_constructed(dimensions):
    _, mapping, _ = fixture()
    scope = (
        mapping.accounting_rules.periods[0]
        .components[1]
        .discontinued_depreciation_exclusion
    )
    with pytest.raises(ValidationError):
        DiscontinuedDepreciationExclusionV1.model_validate(
            {**scope.model_dump(), "dimensions": dimensions}
        )


def test_positive_scoped_use_and_altered_base_or_passage_reference_fail():
    view, mapping, _ = fixture()
    rules = mapping.accounting_rules
    rule = rules.periods[0]
    component = rule.components[1]
    scope = component.discontinued_depreciation_exclusion
    with pytest.raises(ValidationError):
        AccountingComponentV1.model_validate({**component.model_dump(), "sign": 1})
    for changed_scope in (
        scope.model_copy(update={"consolidated_base_fact_digest": "f" * 64}),
        scope.model_copy(
            update={
                "classification_passage": scope.classification_passage.model_copy(
                    update={
                        "exact_quote": "A changed quote of discontinued depreciation for 2023."
                    }
                )
            }
        ),
    ):
        changed_component = component.model_copy(
            update={"discontinued_depreciation_exclusion": changed_scope}
        )
        changed_rule = rule.model_copy(
            update={"components": (rule.components[0], changed_component)}
        )
        changed = mapping.model_copy(
            update={
                "accounting_rules": rules.model_copy(
                    update={"periods": (changed_rule,)}
                )
            }
        )
        with pytest.raises(SnapshotError):
            candidates(view, changed)


def test_ordinary_component_canonical_bytes_omit_new_scope():
    component = AccountingComponentV1(parsed_fact_digest="a" * 64)
    assert canonical_bytes(component) == canonical_bytes(
        {"parsed_fact_digest": "a" * 64, "sign": 1}
    )
