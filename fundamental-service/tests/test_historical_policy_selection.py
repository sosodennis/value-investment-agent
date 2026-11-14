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
from market_policy_fixtures import synthetic_market_inputs


def _at(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=UTC)


def _policy(
    name: str,
    *,
    effective_year: int,
    available_year: int,
    issuer_id: str | None = None,
) -> PolicyRecordV1:
    payload = initial_policy_records()[0].model_dump(mode="python")
    payload["policy_id"] = name
    payload["policy_version"] = name
    payload["effective_at"] = _at(effective_year)
    if issuer_id is not None:
        payload["issuer_id"] = issuer_id
    payload["market_inputs"] = synthetic_market_inputs().model_dump(mode="python")
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
    registry: PolicyRegistry,
    *,
    policy_id: str | None = None,
    issuer_id: str | None = None,
    data_release_manifest_digest: str | None = None,
) -> PolicyRecordV1:
    return registry.select_policy(
        model_id="fcff_dcf",
        model_version="fcff_dcf-v2",
        valuation_timestamp=_at(2016),
        policy_id=policy_id,
        issuer_id=issuer_id,
        data_release_manifest_digest=data_release_manifest_digest,
    )


def test_staged_release_policies_cannot_change_another_release_or_unscoped_reads():
    generic = _policy("fixture-generic", effective_year=2015, available_year=2015)
    scoped_base = _policy(
        "fixture-scoped", effective_year=2014, available_year=2014, issuer_id="issuer-a"
    )
    payload = scoped_base.model_dump(exclude={"policy_digest"})
    payload["data_release_manifest_digest"] = "a" * 64
    scoped = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    for policies in ((generic, scoped), (scoped, generic)):
        registry = PolicyRegistry(initial_model_specs(), policies)
        assert _select(registry, issuer_id="issuer-a") == generic
        assert (
            _select(
                registry, issuer_id="issuer-a", data_release_manifest_digest="b" * 64
            )
            == generic
        )
        assert (
            _select(
                registry, issuer_id="issuer-a", data_release_manifest_digest="a" * 64
            )
            == scoped
        )
        for digest in (None, "b" * 64):
            with pytest.raises(PolicyError) as failure:
                _select(
                    registry,
                    issuer_id="issuer-a",
                    policy_id=scoped.policy_id,
                    data_release_manifest_digest=digest,
                )
            assert failure.value.code == "POLICY_DATA_RELEASE_MISMATCH"
    legacy = generic.model_dump()
    assert "data_release_manifest_digest" not in legacy
    legacy.pop("policy_digest")
    assert sha256_digest(legacy) == generic.policy_digest


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
    payload["market_inputs"] = synthetic_market_inputs().model_dump(mode="python")
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
    policy = _policy("fixture-digest", effective_year=2015, available_year=2015)
    payload = policy.model_dump(mode="python")
    payload["market_inputs"]["evidence"][0]["content_hash"] = "a" * 64
    with pytest.raises(ValueError, match="policy_digest"):
        PolicyRecordV1.model_validate(payload)
    payload["policy_digest"] = sha256_digest(
        {key: value for key, value in payload.items() if key != "policy_digest"}
    )
    changed = PolicyRecordV1.model_validate(payload)
    assert changed.policy_digest != policy.policy_digest


def test_issuer_policy_precedes_generic_policy_without_leaking_between_issuers():
    generic = _policy("fixture-generic", effective_year=2015, available_year=2015)
    issuer_a = _policy(
        "fixture-issuer-a",
        effective_year=2014,
        available_year=2014,
        issuer_id="issuer-a",
    )
    issuer_b = _policy(
        "fixture-issuer-b",
        effective_year=2016,
        available_year=2016,
        issuer_id="issuer-b",
    )
    registry = PolicyRegistry(initial_model_specs(), (generic, issuer_a, issuer_b))

    assert _select(registry, issuer_id="issuer-a") == issuer_a
    assert _select(registry, issuer_id="issuer-b") == issuer_b
    assert _select(registry) == generic
    assert _select(registry, issuer_id="issuer-c") == generic


def test_pinned_issuer_policy_requires_matching_issuer_context():
    issuer_a = _policy(
        "fixture-issuer-a",
        effective_year=2015,
        available_year=2015,
        issuer_id="issuer-a",
    )
    registry = PolicyRegistry(initial_model_specs(), (issuer_a,))

    for issuer_id, code in (
        (None, "POLICY_ISSUER_REQUIRED"),
        ("issuer-b", "POLICY_ISSUER_MISMATCH"),
    ):
        with pytest.raises(PolicyError) as error:
            _select(registry, policy_id=issuer_a.policy_id, issuer_id=issuer_id)
        assert error.value.code == code

    with pytest.raises(PolicyError) as error:
        _select(registry, issuer_id="issuer-b")
    assert error.value.code == "POLICY_NOT_FOUND"


def test_same_issuer_effective_policy_ambiguity_is_not_hidden_by_other_issuers():
    first = _policy(
        "fixture-issuer-a-first",
        effective_year=2015,
        available_year=2015,
        issuer_id="issuer-a",
    )
    second = _policy(
        "fixture-issuer-a-second",
        effective_year=2015,
        available_year=2015,
        issuer_id="issuer-a",
    )
    unrelated = _policy(
        "fixture-issuer-b",
        effective_year=2015,
        available_year=2015,
        issuer_id="issuer-b",
    )
    registry = PolicyRegistry(initial_model_specs(), (first, second, unrelated))

    with pytest.raises(PolicyError) as error:
        _select(registry, issuer_id="issuer-a")
    assert error.value.code == "POLICY_AMBIGUOUS"
    assert _select(registry, issuer_id="issuer-b") == unrelated


def test_unscoped_policy_keeps_legacy_digest_bytes():
    policy = initial_policy_records()[0]
    assert policy.issuer_id is None
    assert "issuer_id" not in policy.model_dump(exclude={"policy_digest"})
    assert sha256_digest(policy.model_dump(exclude={"policy_digest"})) == (
        policy.policy_digest
    )
