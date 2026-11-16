"""Capital assets remain separate from operating value, cash and working capital."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from fundamental_service.accounting_roles import (
    AccountingComponentV1,
    AccountingPeriodRuleV1,
    AccountingPeriodV1,
    AccountingRoleEvidenceV1,
    AccountingRoleRuleSetV1,
)
from fundamental_service.arelle_parser import ParsedXbrlFactV1
from fundamental_service.calculator import CalculationRefusal, calculate
from fundamental_service.contracts import (
    CanonicalFactV1,
    CapitalBridgeAssumptionsV1,
    QualityStatus,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.testsupport import make_valuation
from fundamental_service.verification import (
    compare_artifact,
    independent_calculate,
    invariant_findings,
)
from test_valuation_preparation import _facts, _market_policy, _prepare


@pytest.mark.parametrize("value", [None, "-1", "NaN", "Infinity"])
def test_capital_asset_amount_requires_an_explicit_finite_nonnegative_value(value):
    bridge = make_valuation().assumptions.capital_bridge
    payload = bridge.model_dump()
    payload["non_operating_assets"] = value
    with pytest.raises(ValidationError):
        CapitalBridgeAssumptionsV1.model_validate(payload)
    del payload["non_operating_assets"]
    with pytest.raises(ValidationError):
        CapitalBridgeAssumptionsV1.model_validate(payload)


@pytest.mark.parametrize("model_id", ["fcff_dcf", "transition_fcff_dcf"])
def test_separate_corporate_bonds_raise_equity_once_without_changing_operating_value(
    model_id,
):
    request = make_valuation().model_copy(
        update={"model_id": model_id, "model_version": f"{model_id}-v2"}
    )
    if model_id == "transition_fcff_dcf":
        request = request.model_copy(
            update={
                "historical_facts": (
                    *request.historical_facts,
                    "filed_operating_evidence",
                )
            }
        )
    bridge = request.assumptions.capital_bridge.model_copy(
        update={"cash": Decimal("10283550")}
    )
    request = request.model_copy(
        update={
            "assumptions": request.assumptions.model_copy(
                update={"capital_bridge": bridge}
            )
        }
    ).with_digest()
    before = calculate(request)
    with_bonds = request.model_copy(
        update={
            "input_digest": None,
            "assumptions": request.assumptions.model_copy(
                update={
                    "capital_bridge": bridge.model_copy(
                        update={"non_operating_assets": Decimal("42706080")}
                    )
                }
            ),
        }
    ).with_digest()
    after = calculate(with_bonds)
    assert after.intrinsic_value - before.intrinsic_value == Decimal("42706080")
    assert after.per_share_value - before.per_share_value == Decimal("427060.80")
    assert next(
        n.value for n in after.nodes if n.node_id == "enterprise_value"
    ) == next(n.value for n in before.nodes if n.node_id == "enterprise_value")
    assert (
        after.input_digest != before.input_digest
        and after.result_hash != before.result_hash
    )
    assert after.calculation_version == "calculator-v2"
    assert canonical_bytes(after) == canonical_bytes(calculate(with_bonds))
    reference = independent_calculate(with_bonds)
    assert not compare_artifact(reference, after)
    assert not invariant_findings(with_bonds, reference)


@pytest.mark.parametrize("version", ["fcff_dcf-v1", "fcff_dcf-v3"])
def test_current_graph_cannot_relabel_an_unsupported_model_version(version):
    request = (
        make_valuation().model_copy(update={"model_version": version}).with_digest()
    )
    with pytest.raises(CalculationRefusal) as error:
        calculate(request)
    assert error.value.code == "MODEL_VERSION_UNSUPPORTED"


def test_formal_prepare_preserves_capital_asset_lineage_and_provisional_status():
    facts = tuple(
        f.model_copy(update={"value": Decimal("42706080")})
        if f.normalized_field == "non_operating_assets"
        else f
        for f in _facts()
    )
    result = _prepare(facts, market_policy=_market_policy())
    assert (
        result.status == "prepared"
        and result.quality_status is QualityStatus.PROVISIONAL
    )
    assert result.input.assumptions.capital_bridge.non_operating_assets == Decimal(
        "42706080"
    )
    evidence = next(
        e
        for e in result.assumptions_evidence
        if e.path == "assumptions.capital_bridge.non_operating_assets"
    )
    assert evidence.fact_ids == ("non_operating_assets-2025",)
    assert (
        evidence.source_refs
        and "excluding cash and operating working capital" in evidence.formula
    )
    assert (
        result.preparation_digest
        == _prepare(
            tuple(reversed(facts)), market_policy=_market_policy()
        ).preparation_digest
    )
    assert result.input.provenance.preparation_version == "fcff-forecast-composer-v5"


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "future",
        "conflicting",
        "negative",
        "currency",
        "unit",
        "dimensions",
        "scope",
        "cash_date",
    ],
)
def test_invalid_or_missing_asset_evidence_abstains_without_an_implicit_zero(case):
    facts = list(_facts())
    asset = next(f for f in facts if f.normalized_field == "non_operating_assets")
    facts.remove(asset)
    expected = "NON_OPERATING_ASSET_SCOPE_INVALID"
    if case in {"missing", "future"}:
        expected = "VALUATION_REQUIRED_FACTS_MISSING"
        if case == "future":
            asset = asset.model_copy(
                update={"available_at": asset.available_at.replace(year=2030)}
            )
            facts.append(asset)
    elif case == "conflicting":
        expected = "CAPITAL_FACT_CONFLICT"
        facts.extend(
            (
                asset,
                asset.model_copy(
                    update={"fact_id": "conflict", "value": Decimal("999")}
                ),
            )
        )
    else:
        changes = {
            "negative": {"value": Decimal("-1")},
            "currency": {"currency": "EUR"},
            "unit": {"unit": "shares"},
            "dimensions": {
                "context": asset.context.model_copy(
                    update={"dimensions": ({"name": "segment", "member": "one"},)}
                )
            },
            "scope": {
                "context": asset.context.model_copy(
                    update={"consolidation_scope": "segmented"}
                )
            },
            "cash_date": {"instant": asset.instant.replace(year=2024)},
        }[case]
        facts.append(asset.model_copy(update=changes))
    result = _prepare(tuple(facts), market_policy=_market_policy())
    assert result.status == "abstained" and result.input is None
    assert expected in result.issue_codes
    repeat = _prepare(tuple(reversed(facts)), market_policy=_market_policy())
    assert canonical_bytes(result) == canonical_bytes(repeat)


@pytest.mark.parametrize(
    "other_role",
    [
        "cash_and_equivalents",
        "operating_current_receivables",
        "inventory",
        "contract_assets",
    ],
)
def test_relabelled_cash_or_working_capital_cannot_be_counted_again(other_role):
    facts = tuple(f for f in _facts() if f.normalized_field != "non_operating_assets")
    other = next(
        f for f in facts if f.normalized_field == other_role and f.instant.year == 2025
    )
    asset = other.model_copy(
        update={
            "fact_id": "duplicate-capital-asset",
            "normalized_field": "non_operating_assets",
        }
    )
    result = _prepare((*facts, asset), market_policy=_market_policy())
    assert result.status == "abstained" and result.input is None
    assert "NON_OPERATING_ASSET_OVERLAP" in result.issue_codes


def test_automatic_mapper_has_no_authority_to_infer_complete_nonoperating_scope(
    tmp_path,
):
    from test_automatic_mapping import case, evaluate

    request, store, _, _ = case(
        tmp_path, proposal_changes={"normalized_field": "non_operating_assets"}
    )
    result = evaluate(request, store)
    assert result.status == "abstain" and result.mapping is None
    assert "MAPPING_AUTOMATIC_RULE_UNSUPPORTED" in result.reason_codes


@pytest.mark.parametrize("cash_sign", [1, -1])
def test_computed_assets_distinguish_reused_cash_from_an_explicit_cash_exclusion(
    cash_sign,
):
    facts = tuple(f for f in _facts() if f.normalized_field != "non_operating_assets")
    cash = next(f for f in facts if f.normalized_field == "cash_and_equivalents")
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
            AccountingComponentV1(parsed_fact_digest=sha256_digest(f), sign=sign)
            for f, sign in zip(observations, (1, cash_sign), strict=True)
        ),
        rationale="Synthetic classified securities total with an explicit cash component",
    )
    rules = AccountingRoleRuleSetV1(
        policy_version="synthetic-assets-excluding-cash-owc-v1",
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
        value=Decimal(50) + cash_sign * cash.value,
    )
    concept = "computed:non_operating_assets"
    asset = CanonicalFactV1.model_validate(
        {
            **cash.model_dump(),
            "fact_id": "computed-assets",
            "normalized_field": "non_operating_assets",
            "concept": concept,
            "value": evidence.value,
            "unit": "iso4217:USD",
            "accounting_evidence": evidence,
            "captured_at": cash.available_at,
            "source": cash.source.model_copy(
                update={"available_at": cash.available_at}
            ),
            "context": cash.context.model_copy(
                update={"concept_qname": concept, "unit_qname": "iso4217:USD"}
            ),
        }
    )
    result = _prepare((*facts, asset), market_policy=_market_policy())
    if cash_sign == 1:
        assert (
            result.status == "abstained"
            and "NON_OPERATING_ASSET_OVERLAP" in result.issue_codes
        )
    else:
        assert result.status == "prepared"
        assert result.input.assumptions.capital_bridge.non_operating_assets == Decimal(
            40
        )
