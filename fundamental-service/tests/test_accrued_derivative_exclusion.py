"""Synthetic owner-boundary tests; these grant no real issuer mapping approval."""

from datetime import date
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext

import pytest

from fundamental_service.accounting_roles import (
    AccruedInterestSwapExclusionV1,
    AccountingComponentV1,
    AccountingPeriodRuleV1,
    AccountingPeriodV1,
    DerivativeClassificationPassageV1,
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
    ("us-gaap:BalanceSheetLocationAxis", "example:AccruedAndNoncurrentMember"),
    ("us-gaap:DerivativeByNatureAxis", "example:CounterpartyMember"),
    ("us-gaap:DerivativeInstrumentRiskAxis", "us-gaap:InterestRateSwapMember"),
)
SWAP = "us-gaap:InterestRateDerivativeInstrumentsNotDesignatedAsHedgingInstrumentsLiabilityAtFairValue"


def fixture(*, total_changes=None, noncurrent_changes=None, passage_changes=None):
    view, mapping, security = issuer_rule()
    report = view.originals[0].report
    template = next(f for f in report.facts if f.is_numeric)
    base = template.model_copy(
        update={
            "concept": "us-gaap:AccruedLiabilitiesCurrent",
            "context_id": "base",
            "value": "100000",
            "decimals": "-3",
        }
    )
    total = base.model_copy(
        update={
            "concept": SWAP,
            "context_id": "swap",
            "value": "30000",
            "dimensions": DIMENSIONS,
            "consolidation_scope": "segmented",
            "security_scope": "segmented",
            **(total_changes or {}),
        }
    )
    noncurrent = base.model_copy(
        update={
            "concept": "us-gaap:DerivativeInstrumentsAndHedgesLiabilitiesNoncurrent",
            "context_id": "noncurrent",
            "value": "20000",
            **(noncurrent_changes or {}),
        }
    )
    passage = base.model_copy(
        update={
            "concept": "us-gaap:ScheduleOfDerivativeInstrumentsInStatementOfFinancialPositionFairValueTextBlock",
            "context_id": "classification",
            "value": "In 2023 the interest rate swap is included in Accrued expenses and Other noncurrent liabilities.",
            "unit": None,
            "is_numeric": False,
            "instant": None,
            "period_start": date(2023, 1, 1),
            "period_end": date(2023, 12, 31),
            "decimals": None,
            **(passage_changes or {}),
        }
    )
    exclusion = AccruedInterestSwapExclusionV1(
        dimensions=DIMENSIONS,
        accrued_base_fact_digest=sha256_digest(base),
        noncurrent_fact_digest=sha256_digest(noncurrent),
        classification_passage=DerivativeClassificationPassageV1(
            parsed_fact_digest=sha256_digest(passage), exact_quote=passage.value
        ),
    )
    rule = AccountingPeriodRuleV1(
        period=AccountingPeriodV1(period_end=date(2023, 12, 31), instant=True),
        disposition="derived",
        components=(
            AccountingComponentV1(parsed_fact_digest=sha256_digest(base)),
            AccountingComponentV1(
                parsed_fact_digest=sha256_digest(total),
                sign=-1,
                accrued_interest_swap_exclusion=exclusion,
            ),
            AccountingComponentV1(parsed_fact_digest=sha256_digest(noncurrent)),
        ),
        rationale="Synthetic partial relation only; not an approved operating role.",
    )
    report = report.model_copy(
        update={"facts": (*report.facts, base, total, noncurrent, passage)}
    )
    claim = evaluate_original_issuer(
        report,
        source=view.originals[0].source,
        decision_at=DECISION,
    )
    view = compose_issuer_operating_source((claim,), valuation_timestamp=DECISION)
    rules = mapping.accounting_rules.model_copy(
        update={
            "normalized_field": "accrued_operating_liabilities",
            "periods": (rule,),
            "parser_fact_digest": fact_semantic_digest(report),
        }
    )
    mapping = mapping.model_copy(
        update={
            "source_concept": "computed:accrued_operating_liabilities",
            "normalized_field": "accrued_operating_liabilities",
            "accounting_rules": rules,
            "status": "provisional",
            "confidence": "unresolved",
        }
    )
    return view, mapping, security


def test_provisional_swap_relation_retains_original_dimensions_precision_and_serving_scope():
    view, mapping, security = fixture()
    mapping = CanonicalMappingV1.model_validate_json(canonical_bytes(mapping))
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        (candidate,) = candidates(view, mapping)
    fact = candidate.canonical_fact(quality=QualityStatus.PROVISIONAL)
    restored = CanonicalFactV1.model_validate_json(canonical_bytes(fact))
    assert fact.value == Decimal("90000") and restored == fact
    assert fact.quality is QualityStatus.PROVISIONAL
    assert len(fact.accounting_evidence.source_facts) == 4
    swap = next(f for f in fact.accounting_evidence.source_facts if f.concept == SWAP)
    assert swap.dimensions == DIMENSIONS and swap.decimals == "-3"
    assert swap.consolidation_scope == swap.security_scope == "segmented"
    verify_accounting_role_evidence(fact, mapping, view)
    with pytest.raises(SnapshotError):
        verify_accounting_role_evidence(fact, mapping, security)
    assert candidates(view, mapping) == (candidate,)
    assert sha256_digest(fact) == sha256_digest(restored)


@pytest.mark.parametrize(
    "changes",
    (
        {"entity_identifier": "0000000002"},
        {"unit": "iso4217:EUR"},
        {"instant": date(2022, 12, 31)},
        {"consolidation_scope": "consolidated"},
        {"security_scope": "security"},
        {"dimensions": ()},
        {"dimensions": (("us-gaap:StatementBusinessSegmentsAxis", "example:Other"),)},
        {"concept": "us-gaap:DerivativeAssets"},
        {"value": "NaN"},
        {"value": "-30000"},
        {"value": "130000"},
    ),
)
def test_swap_cannot_escape_source_scope_period_unit_or_accrued_balance(changes):
    view, mapping, _ = fixture(total_changes=changes)
    with pytest.raises(SnapshotError):
        candidates(view, mapping)


@pytest.mark.parametrize(
    "changes",
    (
        {"value": "31000"},
        {"value": "-1"},
        {"concept": "us-gaap:OtherLiabilitiesNoncurrent"},
        {"unit": "iso4217:EUR"},
        {"instant": date(2022, 12, 31)},
        {"entity_identifier": "0000000002"},
        {"dimensions": DIMENSIONS, "consolidation_scope": "segmented"},
    ),
)
def test_noncurrent_pair_must_be_positive_aligned_consolidated_derivative(changes):
    view, mapping, _ = fixture(noncurrent_changes=changes)
    with pytest.raises(SnapshotError):
        candidates(view, mapping)


@pytest.mark.parametrize(
    "changes",
    (
        {"value": "The entity has no interest rate swap liabilities in 2023."},
        {"concept": "us-gaap:UnrelatedTextBlock"},
        {"period_end": date(2022, 12, 31)},
        {"entity_identifier": "0000000002"},
        {"dimensions": DIMENSIONS, "consolidation_scope": "segmented"},
    ),
)
def test_classification_requires_exact_original_passage_with_location_and_period(
    changes,
):
    view, mapping, _ = fixture(passage_changes=changes)
    with pytest.raises(SnapshotError):
        candidates(view, mapping)


def test_missing_or_altered_passage_and_foreign_pair_digest_fail():
    view, mapping, _ = fixture()
    rule = mapping.accounting_rules.periods[0]
    component = rule.components[1]
    scope = component.accrued_interest_swap_exclusion
    for update in (
        {"noncurrent_fact_digest": "a" * 64},
        {"accrued_base_fact_digest": "a" * 64},
        {
            "classification_passage": scope.classification_passage.model_copy(
                update={"exact_quote": "An altered unrelated disclosure in 2023."}
            )
        },
        {
            "classification_passage": scope.classification_passage.model_copy(
                update={"parsed_fact_digest": "a" * 64}
            )
        },
    ):
        altered = component.model_copy(
            update={"accrued_interest_swap_exclusion": scope.model_copy(update=update)}
        )
        changed_rule = rule.model_copy(
            update={"components": (rule.components[0], altered, rule.components[2])}
        )
        changed = mapping.model_copy(
            update={
                "accounting_rules": mapping.accounting_rules.model_copy(
                    update={"periods": (changed_rule,)}
                )
            }
        )
        with pytest.raises(SnapshotError):
            candidates(view, changed)


@pytest.mark.parametrize("index", (0, 2))
def test_base_and_noncurrent_pair_cannot_be_negative_components(index):
    view, mapping, _ = fixture()
    rule = mapping.accounting_rules.periods[0]
    components = tuple(
        c.model_copy(update={"sign": -1}) if i == index else c
        for i, c in enumerate(rule.components)
    )
    rules = mapping.accounting_rules.model_copy(
        update={"periods": (rule.model_copy(update={"components": components}),)}
    )
    with pytest.raises(SnapshotError):
        candidates(view, mapping.model_copy(update={"accounting_rules": rules}))


def test_scoped_swap_is_negative_only_and_does_not_grant_other_role_authority():
    view, mapping, _ = fixture()
    component = mapping.accounting_rules.periods[0].components[1]
    with pytest.raises(ValueError, match="negative component"):
        AccountingComponentV1.model_validate({**component.model_dump(), "sign": 1})
    rules = mapping.accounting_rules.model_copy(
        update={"normalized_field": "current_interest_bearing_debt"}
    )
    changed = mapping.model_copy(
        update={
            "accounting_rules": rules,
            "normalized_field": rules.normalized_field,
            "source_concept": f"computed:{rules.normalized_field}",
        }
    )
    with pytest.raises(SnapshotError, match="instant accrued operating role"):
        candidates(view, changed)


@pytest.mark.parametrize(
    "dimensions",
    (
        DIMENSIONS + (("us-gaap:StatementBusinessSegmentsAxis", "example:Other"),),
        tuple(reversed(DIMENSIONS)),
        (DIMENSIONS[0], DIMENSIONS[0]),
        (DIMENSIONS[0], (DIMENSIONS[-1][0], "us-gaap:CurrencySwapMember")),
        ((DIMENSIONS[0][0], ""), DIMENSIONS[-1]),
    ),
)
def test_exclusion_scope_rejects_segments_other_instruments_or_ambiguous_dimensions(
    dimensions,
):
    _, mapping, _ = fixture()
    scope = (
        mapping.accounting_rules.periods[0]
        .components[1]
        .accrued_interest_swap_exclusion
    )
    with pytest.raises(ValueError):
        AccruedInterestSwapExclusionV1.model_validate(
            {**scope.model_dump(), "dimensions": dimensions}
        )


def test_unset_scope_preserves_existing_component_bytes():
    component = AccountingComponentV1(parsed_fact_digest="a" * 64)
    assert canonical_bytes(component) == canonical_bytes(
        {"parsed_fact_digest": "a" * 64, "sign": 1}
    )


def test_exact_source_set_rejects_missing_observation_or_conflicting_swap():
    view, mapping, _ = fixture()
    report = view.originals[0].report
    total = next(f for f in report.facts if f.concept == SWAP)
    for observations, code in (
        (
            tuple(f for f in report.facts if f != total),
            "ACCOUNTING_ROLE_SOURCE_MISMATCH",
        ),
        (
            (
                *report.facts,
                total.model_copy(update={"value": "31000", "context_id": "conflict"}),
            ),
            "ACCOUNTING_COMPONENT_CONFLICT",
        ),
    ):
        changed_report = report.model_copy(update={"facts": observations})
        claim = evaluate_original_issuer(
            changed_report, source=view.originals[0].source, decision_at=DECISION
        )
        changed_view = compose_issuer_operating_source(
            (claim,), valuation_timestamp=DECISION
        )
        rules = mapping.accounting_rules.model_copy(
            update={"parser_fact_digest": fact_semantic_digest(changed_report)}
        )
        with pytest.raises(SnapshotError) as error:
            candidates(
                changed_view, mapping.model_copy(update={"accounting_rules": rules})
            )
        assert error.value.code == code


def test_noncurrent_pair_is_required_and_swap_cannot_be_counted_twice():
    view, mapping, _ = fixture()
    rule = mapping.accounting_rules.periods[0]
    without_pair = rule.model_copy(update={"components": rule.components[:2]})
    rules = mapping.accounting_rules.model_copy(update={"periods": (without_pair,)})
    with pytest.raises(SnapshotError, match="noncurrent pair"):
        candidates(view, mapping.model_copy(update={"accounting_rules": rules}))
    with pytest.raises(ValueError, match="repeat a source fact"):
        AccountingPeriodRuleV1.model_validate(
            {**rule.model_dump(), "components": (*rule.components, rule.components[1])}
        )


def test_comparative_year_requires_its_year_in_the_original_passage():
    view, mapping, _ = fixture(
        passage_changes={
            "value": "In 2024 the swap is in Accrued expenses and Other noncurrent liabilities."
        }
    )
    with pytest.raises(SnapshotError, match="classification passage"):
        candidates(view, mapping)


@pytest.mark.parametrize("dated,lease", ((True, False), (False, True), (True, True)))
def test_swap_dated_disclosure_and_lease_exclusion_share_one_original(dated, lease):
    from test_accounting_dated_disclosures import _dated_disclosure_fixture
    from test_accounting_roles import _classified_lease_fixture

    view, mapping, _ = fixture()
    original = view.originals[0]
    rule = mapping.accounting_rules.periods[0]
    components = list(rule.components)
    observations = list(original.report.facts)
    expected = Decimal("90000")
    if dated:
        _, dated_report, dated_mapping = _dated_disclosure_fixture()
        component = dated_mapping.accounting_rules.periods[0].components[1]
        passage = next(
            fact
            for fact in dated_report.facts
            if sha256_digest(fact) == component.parsed_fact_digest
        )
        passage = passage.model_copy(
            update={
                "entity_identifier": original.source.cik,
                "security_scope": "unspecified",
            }
        )
        component = component.model_copy(
            update={"parsed_fact_digest": sha256_digest(passage)}
        )
        observations.append(passage)
        components.append(component)
        expected += Decimal("10500000000")
    if lease:
        _, lease_report, _ = _classified_lease_fixture()
        current = next(fact for fact in lease_report.facts if fact.dimensions)
        current = current.model_copy(update={"entity_identifier": original.source.cik})
        observations.append(current)
        components.append(
            AccountingComponentV1(
                parsed_fact_digest=sha256_digest(current),
                sign=-1,
                balance_sheet_location="other_current_liabilities",
            )
        )
        expected -= Decimal("20")
    report = original.report.model_copy(update={"facts": tuple(observations)})
    claim = evaluate_original_issuer(
        report, source=original.source, decision_at=DECISION
    )
    view = compose_issuer_operating_source((claim,), valuation_timestamp=DECISION)
    rule = AccountingPeriodRuleV1.model_validate(
        {
            **rule.model_dump(),
            "components": tuple(components),
        }
    )
    rules = mapping.accounting_rules.model_copy(
        update={
            "periods": (rule,),
            "parser_fact_digest": fact_semantic_digest(report),
        }
    )
    mapping = CanonicalMappingV1.model_validate_json(
        canonical_bytes(mapping.model_copy(update={"accounting_rules": rules}))
    )
    (candidate,) = candidates(view, mapping)
    fact = candidate.canonical_fact(quality=QualityStatus.PROVISIONAL)
    assert fact.value == expected
    assert fact.decimals == (None if lease else -8)
    assert len(fact.accounting_evidence.source_facts) == 4 + int(dated) + int(lease)
    decoded = CanonicalFactV1.model_validate_json(canonical_bytes(fact))
    verify_accounting_role_evidence(decoded, mapping, view)
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        assert candidates(view, mapping) == (candidate,)


def test_lease_scope_preserves_bytes_and_cannot_also_authorize_swap_scope():
    _, mapping, _ = fixture()
    exclusion = (
        mapping.accounting_rules.periods[0]
        .components[1]
        .accrued_interest_swap_exclusion
    )
    old = {
        "parsed_fact_digest": "a" * 64,
        "sign": -1,
        "balance_sheet_location": "other_current_liabilities",
    }
    assert canonical_bytes(AccountingComponentV1(**old)) == canonical_bytes(old)
    with pytest.raises(ValueError):
        AccountingComponentV1(**old, accrued_interest_swap_exclusion=exclusion)
