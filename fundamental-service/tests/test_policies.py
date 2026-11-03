from datetime import datetime, timezone
from decimal import Decimal

import pytest

from fundamental_service.contracts import QualityStatus
from fundamental_service.policies import (
    PolicyRecordV1,
    evaluate_eligibility,
    initial_model_specs,
    resolve_policy,
)
from fundamental_service.testsupport import make_valuation


def policy() -> PolicyRecordV1:
    request = make_valuation()
    base = request.assumptions.model_copy(deep=True)
    payload = {
        "contract_version": "fundamental.v1",
        "policy_id": "policy-v1",
        "policy_version": "policy-v1",
        "profile_id": "us-gaap-public-v1",
        "model_id": "fcff_dcf",
        "assumptions": base,
        "source_refs": ("public-policy",),
        "effective_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "status": "active",
    }
    from fundamental_service.serialization import sha256_digest

    return PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))


def test_only_two_initial_models_and_no_legacy_fallback():
    assert {spec.model_id for spec in initial_model_specs()} == {
        "fcff_dcf",
        "transition_fcff_dcf",
    }


def test_policy_resolution_records_caller_precedence_and_digest():
    request = make_valuation()
    resolved, resolution = resolve_policy(request=request, policy=policy())
    assert resolved.input_digest == resolution.input_digest
    assert resolution.precedence["assumptions.terminal_growth"] == "caller"


def test_missing_or_low_quality_inputs_abstain():
    request = make_valuation()
    result = evaluate_eligibility(
        request=request,
        model=initial_model_specs()[0],
        available_fields={"revenue"},
        quality={"status": QualityStatus.PROVISIONAL},
    )
    assert result.report.status == QualityStatus.ABSTAIN
    assert "MISSING_REQUIRED_FACT" in result.report.issue_codes


def test_policy_digest_is_immutable():
    first = policy()
    altered = first.model_copy(update={"policy_version": "policy-v2"})
    with pytest.raises(ValueError):
        PolicyRecordV1.model_validate(altered.model_dump())


def test_zero_caller_terminal_growth_wins():
    request = make_valuation().model_copy(
        update={
            "assumptions": make_valuation().assumptions.model_copy(
                update={"terminal_growth": Decimal("0")}
            )
        }
    )
    resolved, resolution = resolve_policy(request=request, policy=policy())
    assert resolved.assumptions.terminal_growth == Decimal("0")
    assert resolution.precedence["assumptions.terminal_growth"] == "caller"
