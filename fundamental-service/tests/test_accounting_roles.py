from datetime import date
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext
import json

import pytest

from fundamental_service.accounting_roles import (
    AbsencePassageV1,
    AccountingComponentV1,
    AccountingPeriodRuleV1,
    AccountingPeriodV1,
    AccountingRoleEvidenceV1,
    AccountingRoleRuleSetV1,
    DisclosedAmountV1,
)
from fundamental_service.arelle_parser import (
    ArelleParseReportV1,
    ArelleValidationProfileV1,
    ParsedXbrlFactV1,
    fact_semantic_digest,
)
from fundamental_service.contracts import CanonicalFactV1, QualityStatus
from fundamental_service.facts import (
    CanonicalMappingV1,
    canonical_fact_digest,
    verify_accounting_role_evidence,
)
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_history_composition import _changed, _original
from test_valuation_preparation import _facts
from test_postgres_metadata import DATABASE_URL


def _fixture(*, disposition="derived", altered_fact=None, altered_passage=None):
    if disposition == "dated_disclosure":
        from test_accounting_dated_disclosures import _dated_disclosure_fixture

        return _dated_disclosure_fixture()
    snapshot = _original(2023)
    source = snapshot.source_records[0]
    observations = tuple(
        ParsedXbrlFactV1(
            concept=f"us-gaap:{name}",
            context_id=f"instant-{name}",
            value=value,
            unit="iso4217:USD",
            entity_identifier=snapshot.identity.issuer_id,
            instant=date(2023, 12, 31),
            is_numeric=True,
            consolidation_scope="consolidated",
            security_scope="security",
        )
        for name, value in (("LongTermDebtCurrent", "100"), ("CommercialPaper", "20"))
    )
    passage = ParsedXbrlFactV1(
        concept="us-gaap:PreferredStockTextBlock",
        context_id="annual-policy",
        value="At December 31, 2023, no preferred stock was issued or outstanding.",
        period_start=date(2023, 1, 1),
        period_end=date(2023, 12, 31),
        entity_identifier=snapshot.identity.issuer_id,
        consolidation_scope="consolidated",
    )
    if disposition == "disclosed":
        passage = passage.model_copy(
            update={
                "concept": "us-gaap:ShareBasedCompensationTextBlock",
                "value": "The company recognized total stock-based compensation cost of $2 million during fiscal 2023.",
            }
        )
    if altered_passage:
        passage = passage.model_copy(update=altered_passage)
    if altered_fact:
        observations = (
            observations[0].model_copy(update=altered_fact),
            observations[1],
        )
    report = ArelleParseReportV1(
        filing_path="synthetic-original.htm",
        parser_version=source.parser_version,
        taxonomy_version="us-gaap-2024",
        validation_profile=ArelleValidationProfileV1(
            profile_id="synthetic-parser-report"
        ),
        validation_profile_digest=snapshot.validation_profile_digest,
        facts=(*observations, passage),
        parsed_at=source.captured_at,
        source_content_hash=source.parser_input_hash,
        offline=True,
        validation_engines=("sec-efm", "dqc-us"),
        validation_evidence=("synthetic validation evidence for boundary tests",),
    )
    # Deliberately synthetic: no fake validation engine runs or real release claims.
    report = report.model_copy(
        update={
            "validation_profile": report.validation_profile.model_copy(
                update={"validation_mode": "sec-efm-dqc"}
            )
        }
    )
    period = AccountingPeriodV1(
        period_start=date(2023, 1, 1) if disposition == "disclosed" else None,
        period_end=date(2023, 12, 31),
        instant=disposition != "disclosed",
    )
    rule = AccountingPeriodRuleV1(
        period=period,
        disposition=disposition,
        components=tuple(
            AccountingComponentV1(parsed_fact_digest=sha256_digest(f))
            for f in observations
        )
        if disposition == "derived"
        else (),
        absence_passages=(
            AbsencePassageV1(
                parsed_fact_digest=sha256_digest(passage), exact_quote=passage.value
            ),
        )
        if disposition == "confirmed_absent"
        else (),
        disclosed_amount=DisclosedAmountV1(
            parsed_fact_digest=sha256_digest(passage),
            quote_start=0,
            exact_quote=passage.value,
            amount_start=passage.value.index("$2") + 1,
            amount_token="2",
            scale_start=passage.value.index("million"),
            scale_token="million",
            scale=6,
            unit_start=passage.value.index("$2"),
            unit_quote="$",
            reported_unit="iso4217:USD",
            reported_decimals=-6,
            covered_classes=("all stock-based awards",),
            complete_role=True,
        )
        if disposition == "disclosed"
        else None,
        rationale="Synthetic rule exercises source classification; it is not a reviewed issuer mapping.",
    )
    role = (
        "current_interest_bearing_debt"
        if disposition == "derived"
        else "stock_based_compensation"
        if disposition == "disclosed"
        else "preferred_claims"
    )
    rules = AccountingRoleRuleSetV1(
        policy_version="synthetic-accounting-policy-v1",
        normalized_field=role,
        issuer_id=snapshot.identity.issuer_id,
        security_id=snapshot.identity.security_id,
        accession_number=source.accession_number,
        raw_content_hash=source.content_hash,
        parser_input_hash=source.parser_input_hash,
        parser_fact_digest=fact_semantic_digest(report),
        unit="iso4217:USD",
        currency="USD",
        periods=(rule,),
    )
    mapping = CanonicalMappingV1(
        contract_version="fundamental.v1",
        decision_id=f"synthetic-{role}",
        source_concept=f"computed:{role}",
        normalized_field=role,
        mapping_version="synthetic-mapping-v1",
        confidence="high",
        status="approved",
        reviewer="test-only-reviewer",
        anchor_concept="us-gaap:DebtCurrent",
        evidence_refs=("synthetic-accounting-boundary",),
        accounting_rules=rules,
    )
    integrity = snapshot.sec_integrity_evidence.model_copy(
        update={
            "normalized_fact_digest": fact_semantic_digest(report),
            "archive_fact_digest": fact_semantic_digest(report),
        }
    )
    snapshot = _changed(snapshot, sec_integrity_evidence=integrity)
    return snapshot, report, mapping


def _candidates(snapshot, report, mapping):
    return parsed_facts_to_candidates(
        report,
        source=snapshot.source_records[0],
        issuer_id=snapshot.identity.issuer_id,
        security_id=snapshot.identity.security_id,
        normalized_field=mapping.normalized_field,
        mapping=mapping,
    )


def _classified_lease_fixture(
    *, noncurrent=False, changes=None, classification=True, kind="finance"
):
    snapshot, report, mapping = _fixture()
    total = report.facts[0].model_copy(
        update={
            "concept": "us-gaap:FinanceLeaseLiability"
            if kind == "finance"
            else "us-gaap:OperatingLeaseLiability",
            "value": "100",
        }
    )
    current = total.model_copy(
        update={
            "context_id": "other-current-liabilities",
            "value": "20",
            "dimensions": (
                (
                    "us-gaap:BalanceSheetLocationAxis",
                    "us-gaap:OtherCurrentLiabilitiesMember",
                ),
            ),
            "consolidation_scope": "segmented",
            "security_scope": "segmented",
            **(changes or {}),
        }
    )
    report = report.model_copy(update={"facts": (total, current)})
    scoped = AccountingComponentV1(
        parsed_fact_digest=sha256_digest(current),
        sign=-1 if noncurrent else 1,
        balance_sheet_location="other_current_liabilities" if classification else None,
    )
    rule = AccountingPeriodRuleV1(
        period=AccountingPeriodV1(period_end=date(2023, 12, 31), instant=True),
        disposition="derived" if noncurrent or not classification else "classified",
        components=(
            AccountingComponentV1(parsed_fact_digest=sha256_digest(total)),
            scoped,
        )
        if noncurrent or not classification
        else (scoped,),
        rationale="Test-only current lease classification from a consolidated balance-sheet location.",
    )
    role = ("long_term_" if noncurrent else "current_") + kind + "_lease_liabilities"
    rules = mapping.accounting_rules.model_copy(
        update={
            "normalized_field": role,
            "parser_fact_digest": fact_semantic_digest(report),
            "periods": (rule,),
        }
    )
    mapping = mapping.model_copy(
        update={
            "normalized_field": role,
            "source_concept": "computed:" + role,
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


@pytest.mark.parametrize("noncurrent,expected", [(False, "20"), (True, "80")])
@pytest.mark.parametrize("kind", ["finance", "operating"])
def test_classified_current_lease_and_total_minus_current_keep_original_dimensions(
    noncurrent, expected, kind
):
    snapshot, report, mapping = _classified_lease_fixture(
        noncurrent=noncurrent, kind=kind
    )
    (candidate,) = _candidates(snapshot, report, mapping)
    fact = candidate.canonical_fact(quality=QualityStatus.VERIFIED)
    assert fact.value == Decimal(expected)
    assert fact.context.dimensions == ()
    assert any(f.dimensions for f in fact.accounting_evidence.source_facts)
    restored = CanonicalFactV1.model_validate_json(canonical_bytes(fact))
    assert canonical_fact_digest(restored) == canonical_fact_digest(fact)
    verify_accounting_role_evidence(restored, mapping, snapshot)
    assert _candidates(snapshot, report, mapping) == (candidate,)


@pytest.mark.parametrize(
    "changes",
    [
        {"dimensions": ()},
        {
            "dimensions": (
                (
                    "us-gaap:BalanceSheetLocationAxis",
                    "us-gaap:OtherNoncurrentLiabilitiesMember",
                ),
            )
        },
        {
            "dimensions": (
                ("us-gaap:StatementBusinessSegmentsAxis", "issuer:CloudMember"),
            )
        },
        {
            "dimensions": (
                (
                    "us-gaap:BalanceSheetLocationAxis",
                    "us-gaap:OtherCurrentLiabilitiesMember",
                ),
                ("us-gaap:StatementBusinessSegmentsAxis", "issuer:CloudMember"),
            )
        },
        {"consolidation_scope": "consolidated"},
        {"security_scope": "security"},
        {"concept": "us-gaap:DebtCurrent"},
        {"entity_identifier": "9999999999"},
        {"instant": date(2022, 12, 31)},
        {"unit": "iso4217:EUR"},
    ],
)
def test_lease_classification_cannot_strip_arbitrary_scope_or_misalign_sources(changes):
    snapshot, report, mapping = _classified_lease_fixture(changes=changes)
    with pytest.raises(SnapshotError):
        _candidates(snapshot, report, mapping)


def test_dimensional_lease_sources_require_explicit_mapping_classification():
    snapshot, report, mapping = _classified_lease_fixture(classification=False)
    with pytest.raises(SnapshotError) as error:
        _candidates(snapshot, report, mapping)
    assert error.value.code == "ACCOUNTING_ROLE_SCOPE_MISMATCH"


@pytest.mark.parametrize(
    "role",
    [
        "contract_assets",
        "current_operating_lease_liabilities",
        "long_term_finance_lease_liabilities",
    ],
)
def test_classified_finance_amount_cannot_supply_another_role_or_positive_noncurrent(
    role,
):
    snapshot, report, mapping = _classified_lease_fixture()
    rules = mapping.accounting_rules.model_copy(update={"normalized_field": role})
    mapping = mapping.model_copy(
        update={
            "normalized_field": role,
            "source_concept": "computed:" + role,
            "accounting_rules": rules,
        }
    )
    with pytest.raises(SnapshotError) as error:
        _candidates(snapshot, report, mapping)
    assert error.value.code == "ACCOUNTING_ROLE_SCOPE_MISMATCH"


def test_classified_source_conflicts_are_retained_and_rejected():
    snapshot, report, mapping = _classified_lease_fixture()
    report = report.model_copy(
        update={
            "facts": (
                *report.facts,
                report.facts[-1].model_copy(update={"value": "21"}),
            )
        }
    )
    mapping = mapping.model_copy(
        update={
            "accounting_rules": mapping.accounting_rules.model_copy(
                update={"parser_fact_digest": fact_semantic_digest(report)}
            )
        }
    )
    with pytest.raises(SnapshotError) as error:
        _candidates(snapshot, report, mapping)
    assert error.value.code == "ACCOUNTING_COMPONENT_CONFLICT"


def test_unclassified_components_preserve_their_canonical_serialization():
    component = AccountingComponentV1(parsed_fact_digest="a" * 64)
    assert json.loads(canonical_bytes(component)) == {
        "parsed_fact_digest": "a" * 64,
        "sign": 1,
    }


def test_current_lease_classification_cannot_add_a_total_and_its_current_portion():
    snapshot, report, mapping = _classified_lease_fixture(noncurrent=True)
    rules = mapping.accounting_rules
    rule = rules.periods[0]
    rule = rule.model_copy(
        update={
            "components": (
                rule.components[0],
                rule.components[1].model_copy(update={"sign": 1}),
            )
        }
    )
    role = "current_finance_lease_liabilities"
    mapping = mapping.model_copy(
        update={
            "normalized_field": role,
            "source_concept": "computed:" + role,
            "accounting_rules": rules.model_copy(
                update={"normalized_field": role, "periods": (rule,)}
            ),
        }
    )
    with pytest.raises(SnapshotError) as error:
        _candidates(snapshot, report, mapping)
    assert error.value.code == "ACCOUNTING_ROLE_SCOPE_MISMATCH"


def test_operating_accrual_classification_subtracts_current_lease_amount():
    snapshot, report, mapping = _classified_lease_fixture(noncurrent=True)
    total, current = report.facts
    total = total.model_copy(update={"concept": "us-gaap:OtherLiabilitiesCurrent"})
    report = report.model_copy(update={"facts": (total, current)})
    rules = mapping.accounting_rules
    rule = rules.periods[0]
    rule = rule.model_copy(
        update={
            "components": (
                AccountingComponentV1(parsed_fact_digest=sha256_digest(total)),
                rule.components[1],
            )
        }
    )
    role = "accrued_operating_liabilities"
    mapping = mapping.model_copy(
        update={
            "normalized_field": role,
            "source_concept": "computed:" + role,
            "accounting_rules": rules.model_copy(
                update={
                    "normalized_field": role,
                    "parser_fact_digest": fact_semantic_digest(report),
                    "periods": (rule,),
                }
            ),
        }
    )
    assert _candidates(snapshot, report, mapping)[0].value == Decimal("80")


def test_noncurrent_classification_requires_the_corresponding_lease_total():
    snapshot, report, mapping = _classified_lease_fixture(noncurrent=True)
    total, current = report.facts
    total = total.model_copy(update={"concept": "us-gaap:OtherLiabilitiesCurrent"})
    report = report.model_copy(update={"facts": (total, current)})
    rules = mapping.accounting_rules
    rule = rules.periods[0]
    rule = rule.model_copy(
        update={
            "components": (
                AccountingComponentV1(parsed_fact_digest=sha256_digest(total)),
                rule.components[1],
            )
        }
    )
    mapping = mapping.model_copy(
        update={
            "accounting_rules": rules.model_copy(
                update={
                    "parser_fact_digest": fact_semantic_digest(report),
                    "periods": (rule,),
                }
            )
        }
    )
    with pytest.raises(SnapshotError) as error:
        _candidates(snapshot, report, mapping)
    assert error.value.code == "ACCOUNTING_ROLE_SCOPE_MISMATCH"


@pytest.mark.parametrize("classified", [False, True])
def test_accounting_components_use_highest_xbrl_precision_and_retain_rounded_originals(
    classified,
):
    snapshot, report, mapping = (
        _classified_lease_fixture()
        if classified
        else _fixture(altered_fact={"value": "6693000000", "decimals": "-6"})
    )
    selected = report.facts[-1] if classified else report.facts[0]
    if classified:
        selected = selected.model_copy(update={"value": "6693000000", "decimals": "-6"})
        report = report.model_copy(update={"facts": (report.facts[0], selected)})
        rules = mapping.accounting_rules
        rule = rules.periods[0]
        rule = rule.model_copy(
            update={
                "components": (
                    rule.components[0].model_copy(
                        update={"parsed_fact_digest": sha256_digest(selected)}
                    ),
                )
            }
        )
        mapping = mapping.model_copy(
            update={"accounting_rules": rules.model_copy(update={"periods": (rule,)})}
        )
    rounded = selected.model_copy(update={"value": "6700000000", "decimals": "-8"})
    report = report.model_copy(update={"facts": (*report.facts, rounded)})
    mapping = mapping.model_copy(
        update={
            "accounting_rules": mapping.accounting_rules.model_copy(
                update={"parser_fact_digest": fact_semantic_digest(report)}
            )
        }
    )
    expected = _candidates(snapshot, report, mapping)
    assert expected[0].value == Decimal("6693000000") + (
        Decimal("0") if classified else Decimal("20")
    )
    assert rounded in report.facts
    assert selected in expected[0].accounting_evidence.source_facts
    assert (
        _candidates(
            snapshot,
            report.model_copy(update={"facts": tuple(reversed(report.facts))}),
            mapping,
        )
        == expected
    )
    duplicate_report = report.model_copy(update={"facts": (*report.facts, rounded)})
    duplicate_mapping = mapping.model_copy(
        update={
            "accounting_rules": mapping.accounting_rules.model_copy(
                update={"parser_fact_digest": fact_semantic_digest(duplicate_report)}
            )
        }
    )
    assert (
        _candidates(snapshot, duplicate_report, duplicate_mapping)[0].value
        == expected[0].value
    )
    rules = mapping.accounting_rules
    rule = rules.periods[0]
    rule = rule.model_copy(
        update={
            "components": tuple(
                c.model_copy(update={"parsed_fact_digest": sha256_digest(rounded)})
                if c.parsed_fact_digest == sha256_digest(selected)
                else c
                for c in rule.components
            )
        }
    )
    low_precision = mapping.model_copy(
        update={"accounting_rules": rules.model_copy(update={"periods": (rule,)})}
    )
    with pytest.raises(SnapshotError) as error:
        _candidates(snapshot, report, low_precision)
    assert error.value.code == "ACCOUNTING_COMPONENT_NOT_SELECTED"


def test_equal_precision_component_conflicts_still_refuse():
    snapshot, report, mapping = _fixture(
        altered_fact={"value": "6693000000", "decimals": "-6"}
    )
    report = report.model_copy(
        update={
            "facts": (
                *report.facts,
                report.facts[0].model_copy(update={"value": "6700000000"}),
            )
        }
    )
    mapping = mapping.model_copy(
        update={
            "accounting_rules": mapping.accounting_rules.model_copy(
                update={"parser_fact_digest": fact_semantic_digest(report)}
            )
        }
    )
    with pytest.raises(SnapshotError) as error:
        _candidates(snapshot, report, mapping)
    assert error.value.code == "ACCOUNTING_COMPONENT_CONFLICT"


def test_classified_mapping_stays_provisional_without_review():
    from fundamental_service.facts import select_fact_groups

    snapshot, report, mapping = _classified_lease_fixture()
    mapping = mapping.model_copy(
        update={"status": "provisional", "confidence": "unresolved", "reviewer": None}
    )
    (selection,) = select_fact_groups(
        _candidates(snapshot, report, mapping), snapshot.valuation_timestamp
    )
    assert selection.fact.quality is QualityStatus.PROVISIONAL


@pytest.mark.parametrize(
    "disposition,expected",
    [("derived", "120"), ("confirmed_absent", "0"), ("disclosed", "2000000")],
)
def test_accounting_value_keeps_sources_and_roundtrips(disposition, expected):
    snapshot, report, mapping = _fixture(disposition=disposition)
    (candidate,) = _candidates(snapshot, report, mapping)
    fact = candidate.canonical_fact(quality=QualityStatus.VERIFIED)
    restored = CanonicalFactV1.model_validate_json(canonical_bytes(fact))
    assert fact.value == Decimal(expected)
    assert fact.concept == f"computed:{mapping.normalized_field}"
    assert restored == fact
    assert fact.accounting_evidence.source_facts
    assert fact.accounting_evidence.rule_set == mapping.accounting_rules
    assert fact.source.content_hash == snapshot.source_records[0].content_hash
    verify_accounting_role_evidence(fact, mapping, snapshot)
    assert canonical_fact_digest(fact) == canonical_fact_digest(restored)
    assert _candidates(snapshot, report, mapping) == (candidate,)


@pytest.mark.parametrize(
    "change",
    [
        {"quote_start": 1},
        {"scale_start": 1},
        {"unit_start": 1},
        {"reported_unit": "iso4217:EUR"},
    ],
)
def test_disclosed_amount_requires_exact_original_quote_unit_and_scale_span(change):
    snapshot, report, mapping = _fixture(disposition="disclosed")
    rules = mapping.accounting_rules
    rule = rules.periods[0]
    amount = rule.disclosed_amount.model_copy(update=change)
    mapping = mapping.model_copy(
        update={
            "accounting_rules": rules.model_copy(
                update={
                    "periods": (rule.model_copy(update={"disclosed_amount": amount}),)
                }
            )
        }
    )
    with pytest.raises(SnapshotError, match="exact original period, unit and spans"):
        _candidates(snapshot, report, mapping)


@pytest.mark.parametrize(
    "change",
    [
        {"scale": 3},
        {"reported_decimals": 0},
        {"amount_start": 0},
        {"amount_token": "NaN"},
        {"amount_token": "2e6"},
        {"covered_classes": ()},
        {"complete_role": False},
    ],
)
def test_disclosed_amount_rejects_inconsistent_or_partial_transcription(change):
    _, _, mapping = _fixture(disposition="disclosed")
    data = mapping.accounting_rules.periods[0].disclosed_amount.model_dump()
    with pytest.raises(ValueError):
        DisclosedAmountV1.model_validate({**data, **change})


def test_disclosed_amount_preserves_precision_provisional_quality_and_decimal_context():
    snapshot, report, mapping = _fixture(disposition="disclosed")
    mapping = mapping.model_copy(
        update={"status": "provisional", "confidence": "unresolved"}
    )
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        (candidate,) = _candidates(snapshot, report, mapping)
    fact = candidate.canonical_fact(quality=QualityStatus.PROVISIONAL)
    assert fact.value == Decimal("2000000")
    assert fact.decimals == -6
    assert fact.quality is QualityStatus.PROVISIONAL
    assert CanonicalFactV1.model_validate_json(canonical_bytes(fact)) == fact
    with pytest.raises(ValueError):
        CanonicalFactV1.model_validate_json(
            canonical_bytes(fact.model_copy(update={"decimals": 0}))
        )


def test_existing_period_rule_bytes_omit_unset_disclosed_amount():
    _, _, mapping = _fixture()
    rule = mapping.accounting_rules.periods[0]
    assert "disclosed_amount" not in rule.model_dump(mode="json")


@pytest.mark.parametrize(
    "change",
    [
        {"period_start": date(2022, 1, 1)},
        {"period_end": date(2022, 12, 31)},
        {"entity_identifier": "0000000002"},
        {
            "dimensions": (
                ("us-gaap:AwardTypeAxis", "us-gaap:RestrictedStockUnitsRSUMember"),
            )
        },
        {"consolidation_scope": "segmented"},
        {"is_numeric": True},
    ],
)
def test_disclosed_amount_cannot_relabel_other_period_or_partial_source_scope(change):
    snapshot, report, mapping = _fixture(
        disposition="disclosed", altered_passage=change
    )
    with pytest.raises(SnapshotError):
        _candidates(snapshot, report, mapping)


def test_disclosed_quote_cannot_select_a_substring_of_a_numeric_token():
    _, _, mapping = _fixture(disposition="disclosed")
    amount = mapping.accounting_rules.periods[0].disclosed_amount
    data = amount.model_dump()
    data.update(
        exact_quote=amount.exact_quote.replace("$2", "$12"),
        amount_start=amount.amount_start + 1,
    )
    with pytest.raises(ValueError, match="complete numeric token"):
        DisclosedAmountV1.model_validate(data)


@pytest.mark.parametrize(
    "token,scale_token,scale,precision,expected",
    [
        ("2.5", "million", 6, -5, "2500000"),
        ("-1,250.25", "thousand", 3, -1, "-1250250"),
        ("1.125", "billion", 9, -6, "1125000000"),
        ("123.45", "dollars", 0, 2, "123.45"),
    ],
)
def test_disclosed_literals_retain_grouping_sign_fraction_and_scaled_precision(
    token, scale_token, scale, precision, expected
):
    snapshot, report, mapping = _fixture(disposition="disclosed")
    original = report.facts[-1]
    text = f"The company's total compensation cost was ${token} {scale_token} for fiscal 2023."
    passage = original.model_copy(update={"value": text})
    amount = DisclosedAmountV1(
        parsed_fact_digest=sha256_digest(passage),
        quote_start=0,
        exact_quote=text,
        amount_start=text.index("$") + 1,
        amount_token=token,
        scale_start=text.index(scale_token),
        scale_token=scale_token,
        scale=scale,
        unit_start=text.index("$"),
        unit_quote="$",
        reported_unit="iso4217:USD",
        reported_decimals=precision,
        covered_classes=("all awards",),
        complete_role=True,
    )
    report = report.model_copy(update={"facts": (*report.facts[:-1], passage)})
    rule = mapping.accounting_rules.periods[0].model_copy(
        update={"disclosed_amount": amount}
    )
    rules = mapping.accounting_rules.model_copy(
        update={"periods": (rule,), "parser_fact_digest": fact_semantic_digest(report)}
    )
    mapping = mapping.model_copy(update={"accounting_rules": rules})
    (candidate,) = _candidates(snapshot, report, mapping)
    fact = candidate.canonical_fact(quality=QualityStatus.PROVISIONAL)
    assert fact.value == Decimal(expected)
    assert fact.decimals == precision
    assert canonical_fact_digest(fact) == canonical_fact_digest(
        CanonicalFactV1.model_validate_json(canonical_bytes(fact))
    )


@pytest.mark.parametrize("disposition", ["unknown", "unsupported"])
def test_unresolved_role_produces_no_placeholder(disposition):
    snapshot, report, mapping = _fixture(disposition=disposition)
    assert _candidates(snapshot, report, mapping) == ()


@pytest.mark.parametrize(
    "change",
    [
        {"unit": "iso4217:EUR"},
        {"instant": date(2022, 12, 31)},
        {"entity_identifier": "0000000002"},
        {"consolidation_scope": "segment"},
        {"value": "NaN"},
    ],
)
def test_accounting_components_cannot_mix_period_unit_scope_or_nonfinite_values(change):
    snapshot, report, mapping = _fixture(altered_fact=change)
    with pytest.raises(SnapshotError):
        _candidates(snapshot, report, mapping)


@pytest.mark.parametrize(
    "field,value",
    [
        ("issuer_id", "0000000002"),
        ("security_id", "foreign"),
        ("accession_number", "0000000001-24-000002"),
        ("parser_input_hash", "a" * 64),
        ("raw_content_hash", "b" * 64),
        ("parser_fact_digest", "c" * 64),
    ],
)
def test_rule_cannot_escape_original_identity_or_source(field, value):
    snapshot, report, mapping = _fixture()
    mapping = mapping.model_copy(
        update={
            "accounting_rules": mapping.accounting_rules.model_copy(
                update={field: value}
            )
        }
    )
    with pytest.raises(SnapshotError, match="exact validated original"):
        _candidates(snapshot, report, mapping)


def test_changed_value_or_passage_cannot_survive_canonical_decode():
    snapshot, report, mapping = _fixture(disposition="confirmed_absent")
    (candidate,) = _candidates(snapshot, report, mapping)
    fact = candidate.canonical_fact(quality=QualityStatus.VERIFIED)
    with pytest.raises(ValueError):
        CanonicalFactV1.model_validate_json(
            canonical_bytes(fact.model_copy(update={"value": Decimal("99")}))
        )
    evidence = fact.accounting_evidence
    with pytest.raises(ValueError):
        AccountingRoleEvidenceV1.model_validate_json(
            canonical_bytes(
                evidence.model_copy(
                    update={
                        "source_facts": (
                            evidence.source_facts[0].model_copy(
                                update={
                                    "value": "No statement about preferred stock is provided."
                                }
                            ),
                        )
                    }
                )
            )
        )


def test_direct_fact_and_mapping_serialization_remains_byte_compatible():
    fact = _facts()[0]
    assert "accounting_evidence" not in fact.model_dump(mode="json")
    assert CanonicalFactV1.model_validate_json(canonical_bytes(fact)) == fact
    mapping = CanonicalMappingV1(
        contract_version="fundamental.v1",
        decision_id="direct",
        source_concept="us-gaap:Revenues",
        normalized_field="revenue",
        mapping_version="v1",
        status="provisional",
        confidence="medium",
    )
    assert "accounting_rules" not in mapping.model_dump(mode="json")


def test_changed_integrity_refuses_accounting_value():
    snapshot, report, mapping = _fixture()
    (candidate,) = _candidates(snapshot, report, mapping)
    fact = candidate.canonical_fact(quality=QualityStatus.VERIFIED)
    changed = _changed(
        snapshot,
        sec_integrity_evidence=snapshot.sec_integrity_evidence.model_copy(
            update={"normalized_fact_digest": "e" * 64, "archive_fact_digest": "e" * 64}
        ),
    )
    with pytest.raises(SnapshotError, match="validated original"):
        verify_accounting_role_evidence(fact, mapping, changed)


def test_classification_is_independent_of_callers_decimal_context():
    snapshot, report, mapping = _fixture(
        altered_fact={"value": "100.123456789012345678901234567890123456789"}
    )
    expected = _candidates(snapshot, report, mapping)
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        assert _candidates(snapshot, report, mapping) == expected
    assert expected[0].value == Decimal("120.1234567890123456789012345678901")


@pytest.mark.parametrize(
    "disposition", ["derived", "disclosed", "classified", "dated_disclosure"]
)
@pytest.mark.parametrize("mutation", [None, "mapping", "integrity"])
def test_signed_canary_and_http_read_recheck_accounting_bindings(mutation, disposition):
    from types import SimpleNamespace

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi.testclient import TestClient

    from fundamental_service.app import create_app
    from fundamental_service.data_releases import (
        DataReleaseError,
        DataReleaseManifestV1,
        FactRefV1,
        MappingRefV1,
        SnapshotRefV1,
        sign_data_release_verification,
        sign_mapping_review_evidence,
    )
    from fundamental_service.operations import OperationsConfig
    from fundamental_service.release_runner import DataReleaseCanaryRunner
    from fundamental_service.testsupport import (
        TEST_SERVICE_TOKEN,
        auth_headers,
        make_internal_envelope,
    )
    from test_release_runner import _candidate

    snapshot, report, mapping = (
        _classified_lease_fixture()
        if disposition == "classified"
        else _fixture(disposition=disposition)
    )
    (candidate,) = _candidates(snapshot, report, mapping)
    fact = candidate.canonical_fact(quality=QualityStatus.VERIFIED)
    if mutation == "mapping":
        rule = mapping.accounting_rules.periods[0].model_copy(
            update={"rationale": "Different reviewed classification"}
        )
        mapping = mapping.model_copy(
            update={
                "accounting_rules": mapping.accounting_rules.model_copy(
                    update={"periods": (rule,)}
                )
            }
        )
    elif mutation == "integrity":
        snapshot = _changed(
            snapshot,
            sec_integrity_evidence=snapshot.sec_integrity_evidence.model_copy(
                update={
                    "normalized_fact_digest": "e" * 64,
                    "archive_fact_digest": "e" * 64,
                }
            ),
        )
    manifest, verification, _, _, _, artifacts, roots = _candidate()
    fact_refs = (
        FactRefV1(fact_id=fact.fact_id, fact_digest=canonical_fact_digest(fact)),
    )
    payload = manifest.model_dump(exclude={"manifest_digest"})
    payload.update(
        snapshot_refs=(
            SnapshotRefV1(
                snapshot_id=snapshot.snapshot_id,
                manifest_digest=snapshot.manifest_digest,
                facts=fact_refs,
                fact_set_digest=sha256_digest(fact_refs),
            ),
        ),
        mapping_refs=(
            MappingRefV1(
                mapping_id=mapping.decision_id, mapping_digest=sha256_digest(mapping)
            ),
        ),
        required_fields=(fact.normalized_field,),
    )
    manifest = DataReleaseManifestV1(**payload, manifest_digest=sha256_digest(payload))
    # Disposable test keys prove gates run after signature verification. These
    # fixtures grant no real issuer review or release approval.
    review_payload = verification.mapping_reviews[0].model_dump(exclude={"signature"})
    review_payload.update(
        mapping_id=mapping.decision_id, mapping_digest=sha256_digest(mapping)
    )
    review = sign_mapping_review_evidence(
        review_payload,
        Ed25519PrivateKey.from_private_bytes(b"reviewer-key".ljust(32, b"0")),
    )
    verification_payload = verification.model_dump(
        exclude={"verification_digest", "signature"}
    )
    verification_payload.update(
        manifest_digest=manifest.manifest_digest, mapping_reviews=(review,)
    )
    verification = sign_data_release_verification(
        verification_payload,
        Ed25519PrivateKey.from_private_bytes(b"verifier-key".ljust(32, b"0")),
    )
    snapshots = SimpleNamespace(get=lambda _id: snapshot)
    facts = SimpleNamespace(get=lambda _id: fact, resolve=lambda **_kwargs: (fact,))
    mappings = SimpleNamespace(get_mapping=lambda _id: mapping)
    runner = DataReleaseCanaryRunner(
        snapshot_repository=snapshots,
        fact_repository=facts,
        mapping_reader=mappings,
        artifact_reader=artifacts,
        trust_roots=roots,
    )
    if mutation:
        with pytest.raises(DataReleaseError) as caught:
            runner.validate(manifest, verification)
        assert caught.value.code == "DATA_RELEASE_ACCOUNTING_ROLE_INVALID"
    else:
        assert runner.validate(manifest, verification).checked_fact_digests == (
            canonical_fact_digest(fact),
        )
    app = create_app(
        snapshot_repository=snapshots,
        fact_repository=facts,
        metadata_store=SimpleNamespace(
            get_data_release_manifest=lambda _digest: manifest,
            get_mapping=lambda _id: mapping,
            start=lambda: None,
            close=lambda: None,
            publish_model=lambda *_args, **_kwargs: None,
            publish_policy=lambda *_args, **_kwargs: None,
        ),
        config=OperationsConfig(service_token=TEST_SERVICE_TOKEN),
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/valuation/evidence/facts",
            headers=auth_headers(),
            json=make_internal_envelope(
                {
                    "contract_version": "fundamental.v1",
                    "snapshot_id": snapshot.snapshot_id,
                    "data_release_manifest_digest": manifest.manifest_digest,
                    "model_id": "fcff_dcf",
                }
            ),
        )
    if mutation:
        assert response.status_code == 409
        assert (
            response.json()["error"]["code"]
            == f"ACCOUNTING_ROLE_{mutation.upper()}_MISMATCH"
        )
    else:
        assert response.status_code == 200
        result = response.json()["result"]
        assert result["quality_status"] == "abstain"
        assert (
            result["facts"][0]["accounting_evidence"]
            == fact.model_dump(mode="json")["accounting_evidence"]
        )


@pytest.mark.parametrize(
    "mutation", ["amendment", "parse_only", "future", "missing_fact", "conflict"]
)
def test_invalid_original_and_conflicts_cannot_supply_accounting_roles(mutation):
    snapshot, report, mapping = _fixture()
    if mutation == "amendment":
        source = snapshot.source_records[0].model_copy(
            update={"is_amendment": True, "amendment_scope": "unknown"}
        )
        snapshot = snapshot.model_copy(update={"source_records": (source,)})
    elif mutation == "parse_only":
        report = report.model_copy(
            update={
                "validation_profile": report.validation_profile.model_copy(
                    update={"validation_mode": "parse-only"}
                )
            }
        )
    elif mutation == "future":
        original_rule = mapping.accounting_rules.periods[0]
        future = original_rule.model_copy(
            update={
                "period": AccountingPeriodV1(
                    period_end=date(2027, 12, 31), instant=True
                )
            }
        )
        mapping = mapping.model_copy(
            update={
                "accounting_rules": mapping.accounting_rules.model_copy(
                    update={"periods": (future,)}
                )
            }
        )
    else:
        if mutation == "missing_fact":
            report = report.model_copy(update={"facts": report.facts[1:]})
        else:
            report = report.model_copy(
                update={
                    "facts": (
                        *report.facts,
                        report.facts[0].model_copy(
                            update={"context_id": "contradictory", "value": "999"}
                        ),
                    )
                }
            )
        mapping = mapping.model_copy(
            update={
                "accounting_rules": mapping.accounting_rules.model_copy(
                    update={"parser_fact_digest": fact_semantic_digest(report)}
                )
            }
        )
    with pytest.raises(SnapshotError):
        _candidates(snapshot, report, mapping)


def test_duplicate_component_and_unrelated_absence_period_refuse():
    snapshot, report, mapping = _fixture()
    rule = mapping.accounting_rules.periods[0]
    with pytest.raises(ValueError, match="repeat"):
        AccountingPeriodRuleV1.model_validate(
            {
                **rule.model_dump(),
                "components": (rule.components[0], rule.components[0]),
            }
        )
    snapshot, report, mapping = _fixture(disposition="confirmed_absent")
    passage = report.facts[-1].model_copy(update={"period_end": date(2022, 12, 31)})
    report = report.model_copy(update={"facts": (*report.facts[:-1], passage)})
    rule = mapping.accounting_rules.periods[0].model_copy(
        update={
            "absence_passages": (
                AbsencePassageV1(
                    parsed_fact_digest=sha256_digest(passage), exact_quote=passage.value
                ),
            )
        }
    )
    mapping = mapping.model_copy(
        update={
            "accounting_rules": mapping.accounting_rules.model_copy(
                update={
                    "parser_fact_digest": fact_semantic_digest(report),
                    "periods": (rule,),
                }
            )
        }
    )
    with pytest.raises(SnapshotError, match="exact original passage"):
        _candidates(snapshot, report, mapping)


@pytest.mark.skipif(not DATABASE_URL, reason="isolated PostgreSQL is required")
@pytest.mark.parametrize(
    "disposition", ["derived", "disclosed", "classified", "dated_disclosure"]
)
@pytest.mark.parametrize("omit", [None, "mapping", "original"])
def test_accounting_sources_survive_persistent_restart_and_backup_restore(
    tmp_path, recovery_databases, omit, disposition
):
    import asyncio
    import hashlib

    from fundamental_service.metadata import PostgresMetadataStore, PostgresContentStore
    from fundamental_service.persistence_recovery import (
        RecoveryError,
        export_backup,
        restore_backup,
    )

    source_database, target_database = recovery_databases
    raw = b"synthetic SEC accounting source for persistent boundary acceptance"
    source_hash = hashlib.sha256(raw).hexdigest()
    snapshot, report, mapping = (
        _classified_lease_fixture()
        if disposition == "classified"
        else _fixture(disposition=disposition)
    )
    source = snapshot.source_records[0].model_copy(
        update={"content_hash": source_hash, "parser_input_hash": source_hash}
    )
    report = report.model_copy(update={"source_content_hash": source_hash})
    rules = mapping.accounting_rules.model_copy(
        update={"raw_content_hash": source_hash, "parser_input_hash": source_hash}
    )
    mapping = mapping.model_copy(update={"accounting_rules": rules})
    integrity = snapshot.sec_integrity_evidence.model_copy(
        update={
            "raw_content_hash": source_hash,
            "parser_input_hash": source_hash,
            "normalized_content_hash": source_hash,
            "archive_member_hash": source_hash,
        }
    )
    snapshot = _changed(
        snapshot, source_records=(source,), sec_integrity_evidence=integrity
    )
    (candidate,) = _candidates(snapshot, report, mapping)
    fact = candidate.canonical_fact(quality=QualityStatus.VERIFIED)
    store = PostgresMetadataStore(source_database, auto_migrate=True)
    store.start()
    content_root = tmp_path / "source-content"
    try:
        content = PostgresContentStore(content_root, store)
        assert content.put(raw, media_type=source.media_type) == source_hash
        if omit != "original":
            store.publish_snapshot(snapshot)
        if omit != "mapping":
            store.publish_mapping(mapping)
        store.publish_fact(fact)
        assert store.get_fact(fact.fact_id) == fact
    finally:
        store.close()
    backups = tmp_path / "backups"
    if omit:
        with pytest.raises(RecoveryError, match="retained mapping|original snapshot"):
            asyncio.run(
                export_backup(
                    source_database, content_root, backups, source_revision="1" * 40
                )
            )
        assert not tuple(backups.glob("*/manifest.json"))
        return
    backup = asyncio.run(
        export_backup(source_database, content_root, backups, source_revision="1" * 40)
    )
    repeated = asyncio.run(
        export_backup(source_database, content_root, backups, source_revision="1" * 40)
    )
    assert (
        repeated.manifest_digest == backup.manifest_digest and repeated.wrote is False
    )
    bundle = backups / backup.manifest_digest
    target_root = tmp_path / "target-content"
    restored = asyncio.run(
        restore_backup(
            target_database, target_root, bundle, manifest_digest=backup.manifest_digest
        )
    )
    assert restored.wrote is True
    repeated_restore = asyncio.run(
        restore_backup(
            target_database, target_root, bundle, manifest_digest=backup.manifest_digest
        )
    )
    assert repeated_restore.wrote is False
    store = PostgresMetadataStore(target_database, auto_migrate=False)
    store.start()
    try:
        restored_fact = store.get_fact(fact.fact_id)
        restored_mapping = store.get_mapping(mapping.decision_id)
        restored_snapshot = store.get_snapshot(snapshot.snapshot_id)
        assert canonical_fact_digest(restored_fact) == canonical_fact_digest(fact)
        assert restored_fact.accounting_evidence == fact.accounting_evidence
        verify_accounting_role_evidence(
            restored_fact, restored_mapping, restored_snapshot
        )
    finally:
        store.close()
