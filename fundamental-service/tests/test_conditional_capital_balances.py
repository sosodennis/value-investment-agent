"""Unknown balances remain explicit conditional operands through owner admission."""

from decimal import Decimal
from itertools import combinations

import pytest

from fundamental_service.conditional_capital_balances import (
    CAPITAL_BALANCE_ROLES,
    CapitalBalanceHypothesesV1,
    CapitalBalanceScenarioV1,
)
from fundamental_service.conditional_capital_contracts import (
    ConditionalCapitalPolicyV1,
)
from fundamental_service.conditional_capital_preparation import (
    bind_conditional_capital_recipe,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.valuation_requirements import (
    automatic_source_requirements_profile,
    source_preparation_requirements_profile,
)
from test_conditional_capital import _case
from test_conditional_capital_preparation import recipe


def balance_hypotheses(fields=CAPITAL_BALANCE_ROLES):
    return CapitalBalanceHypothesesV1(
        unknown_fields=fields,
        limitations=(
            "These disjoint bridge amounts are explicit what-if assumptions only, not measured amounts, calibrated estimates or economic bounds.",
        ),
        scenarios=tuple(
            CapitalBalanceScenarioV1(
                name=name,
                values={role: Decimal(index + 1) for role in fields},
                rationale={
                    role: "Hypothetical complete role amount excluding other bridge operands; the available original evidence does not establish this amount."
                    for role in fields
                },
            )
            for index, name in enumerate(("base", "downside", "upside"))
        ),
    )


def test_missing_balances_require_explicit_hypotheses_and_preserve_unknowns():
    policy, facts, snapshot = _case()
    fields = CAPITAL_BALANCE_ROLES
    retained = tuple(f for f in facts if f.normalized_field not in fields)
    original = bind_conditional_capital_recipe(
        recipe(policy), retained, snapshot=snapshot
    )
    assert original.assessment is None and set(original.missing_evidence) == set(fields)
    configured = recipe(policy).model_copy(
        update={"balance_hypotheses": balance_hypotheses()}
    )
    bound = bind_conditional_capital_recipe(configured, retained, snapshot=snapshot)
    assert not bound.issue_codes and not bound.missing_evidence
    assert bound.policy.complete_capital_claims is False
    assert set(bound.policy.unknowns) == {*policy.unknowns, *fields}
    assert not set(fields) & set(bound.policy.observations)
    assert {f.fact_id for f in bound.assessment.source_facts} == {
        f.fact_id for f in retained
    }
    assert len({sha256_digest(s.bridge) for s in bound.assessment.scenarios}) == 3
    for scenario in bound.assessment.scenarios:
        amounts = next(
            s.values
            for s in configured.balance_hypotheses.scenarios
            if s.name == scenario.hypothesis.name
        )
        assert scenario.bridge.non_operating_assets == amounts["non_operating_assets"]
        assert (
            scenario.bridge.non_controlling_interest
            == amounts["noncontrolling_interests"]
        )
    assert canonical_bytes(bound) == canonical_bytes(
        bind_conditional_capital_recipe(configured, retained[::-1], snapshot=snapshot)
    )


@pytest.mark.parametrize("role", CAPITAL_BALANCE_ROLES)
def test_observed_balances_cannot_be_replaced_by_scenarios(role):
    policy, facts, snapshot = _case()
    configured = recipe(policy).model_copy(
        update={"balance_hypotheses": balance_hypotheses((role,))}
    )
    bound = bind_conditional_capital_recipe(configured, facts, snapshot=snapshot)
    assert bound.assessment is None
    assert "CONDITIONAL_CAPITAL_OBSERVED_CLAIM_CONFLICT" in bound.issue_codes


@pytest.mark.parametrize(
    "failure",
    [
        "negative",
        "infinite",
        "missing_role",
        "extra_role",
        "rationale",
        "sensitivity",
        "unknowns",
        "version",
        "interpretation",
    ],
)
def test_malformed_or_unexplained_balance_hypotheses_are_rejected(failure):
    payload = balance_hypotheses().model_dump()
    row = payload["scenarios"][0]
    role = CAPITAL_BALANCE_ROLES[0]
    if failure in {"negative", "infinite"}:
        row["values"][role] = Decimal("-1" if failure == "negative" else "NaN")
    elif failure == "missing_role":
        del row["values"][role]
    elif failure == "extra_role":
        row["values"]["cash_and_equivalents"] = Decimal(1)
    elif failure == "rationale":
        row["rationale"][role] = "unknown"
    elif failure == "sensitivity":
        for scenario in payload["scenarios"]:
            scenario["values"][role] = Decimal(0)
    elif failure == "unknowns":
        payload["unknown_fields"] = tuple(reversed(CAPITAL_BALANCE_ROLES))
    elif failure == "version":
        payload["protocol"] = "unapproved-v0"
    else:
        payload["interpretation"] = "calibrated_estimate"
    with pytest.raises(ValueError):
        CapitalBalanceHypothesesV1.model_validate(payload)


@pytest.mark.parametrize("with_forward", [False, True])
def test_source_profiles_only_relax_declared_supported_balance_roles(with_forward):
    legacy = source_preparation_requirements_profile(
        "fcff_dcf", conditional_capital=True, conditional_reinvestment=with_forward
    )
    for size in range(1, len(CAPITAL_BALANCE_ROLES) + 1):
        for fields in combinations(CAPITAL_BALANCE_ROLES, size):
            profile = source_preparation_requirements_profile(
                "fcff_dcf",
                conditional_capital=True,
                conditional_reinvestment=with_forward,
                hypothetical_balance_fields=fields,
            )
            assert set(profile.required_fact_fields) == set(
                legacy.required_fact_fields
            ) - set(fields)
            assert set(fields) <= set(profile.supporting_fact_fields)
            assert (
                automatic_source_requirements_profile("fcff_dcf", profile.digest)
                == profile
            )
            assert profile.supported_history_threshold is None


def test_policy_cannot_hide_a_hypothetical_balance_from_its_unknown_inventory():
    policy, _, _ = _case()
    extension = balance_hypotheses()
    payload = policy.model_dump() | {
        "balance_hypotheses": extension,
        "observations": {
            role: ref
            for role, ref in policy.observations.items()
            if role not in extension.unknown_fields
        },
    }
    with pytest.raises(ValueError, match="retain every unresolved"):
        ConditionalCapitalPolicyV1.model_validate(payload)


@pytest.mark.parametrize(
    "role",
    [
        "cash_and_equivalents",
        "common_shares_outstanding",
        "long_term_interest_bearing_debt",
    ],
)
def test_hypotheses_cannot_relax_other_observed_roles(role):
    payload = balance_hypotheses().model_dump()
    payload["unknown_fields"] = (role,)
    with pytest.raises(ValueError):
        CapitalBalanceHypothesesV1.model_validate(payload)
    with pytest.raises(ValueError):
        source_preparation_requirements_profile(
            "fcff_dcf", conditional_capital=True, hypothetical_balance_fields=(role,)
        )


def test_composite_working_capital_still_requires_its_observed_debt_exclusion(tmp_path):
    from fundamental_service.data_releases import DataReleaseError
    from test_conditional_capital_composer import _prepared_case

    with pytest.raises(DataReleaseError) as error:
        _prepared_case(tmp_path, balance_hypotheses=balance_hypotheses())
    assert error.value.code == "DATA_RELEASE_WORKING_CAPITAL_UNBOUND"


@pytest.mark.parametrize("forward", [False, True])
def test_formal_composer_calculates_and_retains_explicit_balance_scenarios(
    tmp_path, forward
):
    from test_conditional_capital_composer import _calculate, _prepared_case
    from test_conditional_reinvestment_composer import _prepared

    fields = (
        CAPITAL_BALANCE_ROLES
        if forward
        else ("non_operating_assets", "noncontrolling_interests")
    )
    hypotheses = balance_hypotheses(fields)
    _, client, _, prepared = (_prepared if forward else _prepared_case)(
        tmp_path, balance_hypotheses=hypotheses
    )
    assert (
        prepared.status == "prepared" and prepared.quality_status.value == "provisional"
    )
    assert set(fields) <= set(prepared.missing_evidence)
    assert prepared.conditional_capital.policy.balance_hypotheses == hypotheses
    value = prepared.input
    response = _calculate(client, value)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert (
        result["status"] == "provisional"
        and result["base"]["per_share_value"] is not None
    )
    assert len(result["scenario_results"]) == 3
    for row, scenario in zip(
        result["scenario_results"], prepared.conditional_capital.scenarios, strict=True
    ):
        assert row["assumptions"]["capital_bridge"] == scenario.bridge.model_dump(
            mode="json"
        )
    repeat = _calculate(client, value)
    assert repeat.status_code == 200 and repeat.json()["result"] == result
