"""Accounting coverage is checked independently of caller claims and signatures."""

import pytest

from fundamental_service.data_releases import DataReleaseError
from fundamental_service.serialization import canonical_bytes
from fundamental_service.working_capital import (
    assess_composite_working_capital,
    canonical_working_capital_inputs,
)
from test_issuer_operating_release import fixture, inventory, resign
from test_working_capital import _fact_for, _facts, _input, _snapshot


@pytest.mark.parametrize(
    "role,reason",
    (
        ("operating_current_payables", "ROLE_UNSUPPORTED"),
        ("issuer_specific_current_financing", "ROLE_UNSUPPORTED"),
        ("cash_and_equivalents", "COVERAGE_MISMATCH"),
        ("current_finance_lease_liabilities", "COVERAGE_MISMATCH"),
        ("cash_and_short_term_investments", "COVERAGE_MISMATCH"),
    ),
)
def test_reported_fact_cannot_claim_another_accounting_class(role, reason):
    policy = _input()
    policy = policy.model_copy(
        update={
            "exclusions": tuple(
                item.model_copy(update={"mapped_fact_role": role})
                if item.account_class == "current_interest_bearing_debt"
                else item
                for item in policy.exclusions
            )
        }
    )
    facts = tuple(
        fact.model_copy(update={"normalized_field": role})
        if fact.normalized_field == "current_interest_bearing_debt"
        else fact
        for fact in _facts()
    )
    result = assess_composite_working_capital(policy, facts, snapshot=_snapshot())
    repeat = assess_composite_working_capital(
        policy, tuple(reversed(facts)), snapshot=_snapshot()
    )
    assert result.status == "abstained"
    assert result.value is None
    assert result.sensitivity == ()
    assert any(
        code.startswith(f"WORKING_CAPITAL_EXCLUSION_{reason}:")
        for code in result.missing_evidence
    )
    assert {fact.fact_id for fact in result.source_facts} == set(policy.fact_ids)
    assert canonical_bytes(result) == canonical_bytes(repeat)


def test_direct_and_supported_combined_cash_coverage_have_equal_values():
    combined = _input()
    cash = combined.exclusions[0]
    direct = combined.model_copy(
        update={
            "exclusions": (
                *(
                    cash.model_copy(
                        update={
                            "account_class": field,
                            "mapped_fact_role": field,
                            "fact_id": f"{field}-2025",
                            "covered_classes": (field,),
                        }
                    )
                    for field in ("cash_and_equivalents", "short_term_investments")
                ),
                *combined.exclusions[1:],
            )
        }
    )
    facts = (
        *(_facts()[:2]),
        _fact_for("cash_and_equivalents", "10"),
        _fact_for("short_term_investments", "5"),
        *(_facts()[3:]),
    )
    result = assess_composite_working_capital(direct, facts, snapshot=_snapshot())
    reference = assess_composite_working_capital(
        combined, _facts(), snapshot=_snapshot()
    )
    assert result.status == reference.status == "estimated"
    assert result.value == reference.value
    assert result.sensitivity == reference.sensitivity
    assert result.input_digest != reference.input_digest


@pytest.mark.parametrize(
    "other_role",
    ("current_finance_lease_liabilities", "cash_and_equivalents"),
)
def test_trusted_signature_cannot_publish_swapped_accounting_coverage(
    tmp_path, other_role
):
    bundle, service, _, _, store = fixture(tmp_path, composite=True)
    policy = bundle.manifest.working_capital_inputs[0]
    by_role = {item.mapped_fact_role: item for item in policy.exclusions}
    debt = "current_interest_bearing_debt"
    replacements = {debt: by_role[other_role], other_role: by_role[debt]}
    altered = policy.model_copy(
        update={
            "exclusions": tuple(
                item.model_copy(
                    update={
                        "mapped_fact_role": replacements[
                            item.mapped_fact_role
                        ].mapped_fact_role,
                        "fact_id": replacements[item.mapped_fact_role].fact_id,
                    }
                )
                if item.mapped_fact_role in replacements
                else item
                for item in policy.exclusions
            )
        }
    )
    signed = resign(
        bundle,
        working_capital_inputs=canonical_working_capital_inputs(
            (altered, *bundle.manifest.working_capital_inputs[1:])
        ),
    )
    before = inventory(store.root)
    with pytest.raises(DataReleaseError) as error:
        service.publish(signed)
    assert error.value.code == "DATA_RELEASE_WORKING_CAPITAL_INVALID"
    assert "WORKING_CAPITAL_EXCLUSION_COVERAGE_MISMATCH:" in str(error.value)
    assert inventory(store.root) == before
