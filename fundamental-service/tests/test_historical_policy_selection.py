"""Synthetic policy records exercise selection; they are not approved evidence."""

from datetime import UTC, datetime

import pytest

from fundamental_service.policies import (
    PolicyError,
    PolicyRecordV1,
    PolicyRegistry,
    initial_model_specs,
    initial_policy_records,
)
from fundamental_service.serialization import sha256_digest


def _at(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=UTC)


def _policy(name: str, *, effective_year: int, available_year: int) -> PolicyRecordV1:
    payload = initial_policy_records()[0].model_dump(mode="python")
    payload["policy_id"] = name
    payload["policy_version"] = name
    payload["effective_at"] = _at(effective_year)
    market = payload["market_inputs"]
    market["policy_version"] = name
    for item in market["evidence"]:
        item["as_of"] = _at(available_year)
        item["available_at"] = _at(available_year)
    payload["policy_digest"] = sha256_digest(
        {key: value for key, value in payload.items() if key != "policy_digest"}
    )
    return PolicyRecordV1.model_validate(payload)


def _select(
    registry: PolicyRegistry, *, policy_id: str | None = None
) -> PolicyRecordV1:
    return registry.select_policy(
        model_id="fcff_dcf",
        model_version="fcff_dcf-v1",
        valuation_timestamp=_at(2016),
        policy_id=policy_id,
    )


def test_selection_uses_latest_available_evidence_independent_of_record_order() -> None:
    old = _policy("fixture-old", effective_year=2013, available_year=2013)
    eligible = _policy("fixture-eligible", effective_year=2015, available_year=2015)
    future = _policy("fixture-future", effective_year=2016, available_year=2025)
    outputs = []
    for records in ((old, eligible, future), (future, eligible, old)):
        registry = PolicyRegistry(initial_model_specs(), records)
        selected = _select(registry)
        assert selected == eligible
        assert selected.market_inputs is not None
        assert all(
            item.captured_at > _at(2016) for item in selected.market_inputs.evidence
        )
        outputs.append(sha256_digest(selected))
    assert outputs[0] == outputs[1]


def test_explicit_pin_cannot_bypass_future_market_evidence() -> None:
    future = _policy("fixture-future", effective_year=2015, available_year=2025)
    registry = PolicyRegistry(initial_model_specs(), (future,))
    with pytest.raises(PolicyError) as error:
        _select(registry, policy_id=future.policy_id)
    assert error.value.code == "POLICY_NOT_EFFECTIVE"
    with pytest.raises(PolicyError) as error:
        _select(registry)
    assert error.value.code == "POLICY_NOT_FOUND"


def test_one_future_role_disqualifies_the_complete_market_policy() -> None:
    payload = _policy(
        "fixture-mixed", effective_year=2015, available_year=2015
    ).model_dump(mode="python")
    payload["market_inputs"]["evidence"][-1]["available_at"] = _at(2025)
    payload["policy_digest"] = sha256_digest(
        {key: value for key, value in payload.items() if key != "policy_digest"}
    )
    registry = PolicyRegistry(
        initial_model_specs(), (PolicyRecordV1.model_validate(payload),)
    )
    with pytest.raises(PolicyError) as error:
        _select(registry)
    assert error.value.code == "POLICY_NOT_FOUND"


def test_equal_effective_eligible_policies_require_an_explicit_pin() -> None:
    first = _policy("fixture-first", effective_year=2015, available_year=2015)
    second = _policy("fixture-second", effective_year=2015, available_year=2015)
    for records in ((first, second), (second, first)):
        registry = PolicyRegistry(initial_model_specs(), records)
        with pytest.raises(PolicyError) as error:
            _select(registry)
        assert error.value.code == "POLICY_AMBIGUOUS"
        assert _select(registry, policy_id=first.policy_id) == first


def test_legacy_digest_cannot_leave_market_evidence_unbound() -> None:
    payload = initial_policy_records()[0].model_dump(mode="python")
    payload["policy_digest"] = sha256_digest(
        {
            key: value
            for key, value in payload.items()
            if key not in {"policy_digest", "market_inputs"}
        }
    )
    with pytest.raises(ValueError, match="policy_digest"):
        PolicyRecordV1.model_validate(payload)
    payload["market_inputs"] = None
    PolicyRecordV1.model_validate(payload)


def test_recomputed_policy_digest_changes_when_source_evidence_changes() -> None:
    policy = initial_policy_records()[0]
    payload = policy.model_dump(mode="python")
    payload["market_inputs"]["evidence"][0]["content_hash"] = "a" * 64
    with pytest.raises(ValueError, match="policy_digest"):
        PolicyRecordV1.model_validate(payload)
    payload["policy_digest"] = sha256_digest(
        {key: value for key, value in payload.items() if key != "policy_digest"}
    )
    changed = PolicyRecordV1.model_validate(payload)
    assert changed.policy_digest != policy.policy_digest
