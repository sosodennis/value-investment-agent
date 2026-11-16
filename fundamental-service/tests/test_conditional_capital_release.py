"""Signed releases bind hypothetical capital without weakening exact source gates."""

from datetime import timedelta
from decimal import Decimal

import pytest

from fundamental_service.conditional_capital import assess_conditional_capital
from fundamental_service.conditional_capital_contracts import (
    OBSERVED_CAPITAL_FIELDS,
    UNRESOLVED_CAPITAL_FIELDS,
    CapitalObservationRefV1,
    ConditionalCapitalPolicyV1,
)
from fundamental_service.contracts import CanonicalFactV1, SourceSnapshotV1
from fundamental_service.data_releases import (
    DataReleaseError,
    DataReleaseManifestV1,
    IssuerOperatingReleaseManifestV1,
)
from fundamental_service.equity_dilution import AWARD_FACT_FIELDS
from fundamental_service.equity_award_evidence import EQUITY_DILUTION_ARTIFACT_ROLE
from fundamental_service.facts import (
    FilesystemCanonicalFactRepository,
    canonical_fact_digest,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import FilesystemSnapshotRepository
from fundamental_service.valuation_release_inputs import (
    valuation_release_conditional_capital,
    valuation_release_requirements,
)
from fundamental_service.valuation_requirements import (
    conditional_capital_requirements_profile,
    valuation_requirements_profile,
)
from equity_award_fixtures import award_evidence
from test_api import _release_manifest_for
from test_conditional_capital import _case
from test_preparation_runner import _reviewed_candidate
from test_valuation_release_inputs import _valuation_fixture, _manifest_with


def _conditional_fixture(tmp_path, *, sec_profile=False, balance_hypotheses=None):
    balance_fields = balance_hypotheses.unknown_fields if balance_hypotheses else ()
    fixture = _valuation_fixture(tmp_path, sec_profile=sec_profile)
    payload = fixture.snapshot.model_dump(exclude={"manifest_digest"})
    payload["source_records"] = tuple(
        source.model_copy(update={"source_id": "sec-filing"})
        for source in fixture.snapshot.source_records
    )
    snapshot = SourceSnapshotV1(
        **payload,
        manifest_digest=sha256_digest(
            {key: value for key, value in payload.items() if key != "snapshot_id"}
        ),
    )
    facts = []
    for fact in fixture.stored:
        if fact.normalized_field in (
            *UNRESOLVED_CAPITAL_FIELDS,
            *AWARD_FACT_FIELDS,
            *balance_fields,
        ):
            continue
        payload = fact.model_dump()
        payload["context"]["entity_scope"] = snapshot.identity.issuer_id
        if fact.normalized_field in OBSERVED_CAPITAL_FIELDS:
            if fact.normalized_field == "common_shares_outstanding":
                payload.update(unit="shares", currency=None)
                payload["context"]["unit_qname"] = "shares"
        facts.append(CanonicalFactV1.model_validate(payload))
    dilution = award_evidence(snapshot)
    facts.extend(dilution.facts)
    facts = tuple(facts)
    fixture.snapshot = snapshot
    fixture.snapshots = FilesystemSnapshotRepository(tmp_path / "conditional-snapshots")
    fixture.snapshots.publish(snapshot)
    fixture.facts = FilesystemCanonicalFactRepository(tmp_path / "conditional-facts")
    for fact in facts:
        fixture.facts.publish(fact)
    fixture.mappings = {
        key: mapping
        for key, mapping in fixture.mappings.items()
        if mapping.normalized_field not in UNRESOLVED_CAPITAL_FIELDS
    }
    refs = tuple(
        ref
        for ref in fixture.manifest.artifact_refs
        if ref.role != EQUITY_DILUTION_ARTIFACT_ROLE
    )
    template, _, _ = _case()
    latest = {
        field: max(
            (fact for fact in facts if fact.normalized_field == field),
            key=lambda fact: fact.instant,
        )
        for field in OBSERVED_CAPITAL_FIELDS
        if field not in balance_fields
    }

    def reference(fact):
        return CapitalObservationRefV1(
            fact_id=fact.fact_id, fact_digest=canonical_fact_digest(fact)
        )

    policy = ConditionalCapitalPolicyV1.model_validate(
        template.model_dump()
        | {
            "mapping_version": fixture.manifest.valuation_working_capital_policy.mapping_version,
            "snapshot_manifest_digest": snapshot.manifest_digest,
            "issuer_id": snapshot.identity.issuer_id,
            "security_id": snapshot.identity.security_id,
            "valuation_timestamp": snapshot.valuation_timestamp,
            "observations": {field: reference(fact) for field, fact in latest.items()},
            "supporting_observations": tuple(
                reference(fact)
                for fact in facts
                if fact.normalized_field in AWARD_FACT_FIELDS
            ),
            "balance_hypotheses": balance_hypotheses,
            "unknowns": (*template.unknowns, *balance_fields),
        }
    )
    profile = conditional_capital_requirements_profile(
        "fcff_dcf", composite_inputs=True, hypothetical_balance_fields=balance_fields
    )
    fixture.manifest = _manifest_with(
        _release_manifest_for(snapshot, facts),
        mapping_refs=tuple(
            ref
            for ref in fixture.manifest.mapping_refs
            if ref.mapping_id in fixture.mappings
        ),
        required_fields=profile.required_fact_fields,
        artifact_refs=refs,
        valuation_working_capital_policy=fixture.manifest.valuation_working_capital_policy,
        conditional_capital_policies=(policy,),
    )
    fixture.stored = facts
    fixture.capital_policy = policy
    return fixture


def _assess(fixture, *, manifest=None, facts=None, snapshot=None, mapping_version=None):
    return valuation_release_conditional_capital(
        manifest or fixture.manifest,
        snapshot or fixture.snapshot,
        facts if facts is not None else fixture.stored,
        mapping_version=mapping_version
        or fixture.manifest.valuation_working_capital_policy.mapping_version,
    )


def test_signed_conditional_release_reproduces_exact_assessor_and_canary(tmp_path):
    fixture = _conditional_fixture(tmp_path)
    candidate, canary = _reviewed_candidate(fixture)
    first = canary.validate(candidate.manifest, candidate.verification)
    assert first == canary.validate(candidate.manifest, candidate.verification)
    expected = assess_conditional_capital(
        fixture.capital_policy,
        fixture.stored,
        snapshot=fixture.snapshot,
        mapping_version=fixture.capital_policy.mapping_version,
    )
    assert _assess(fixture) == expected
    assert _assess(fixture, facts=tuple(reversed(fixture.stored))) == expected
    assert not expected.policy.complete_capital_claims
    assert not expected.policy.complete_award_inventory
    profile = valuation_release_requirements(candidate.manifest, "fcff_dcf")
    assert profile == conditional_capital_requirements_profile(
        "fcff_dcf", composite_inputs=True
    )
    assert set(UNRESOLVED_CAPITAL_FIELDS) <= set(profile.supporting_fact_fields)
    assert not set(UNRESOLVED_CAPITAL_FIELDS) & set(profile.required_fact_fields)
    assert profile.supported_history_threshold is None


def test_conditional_policy_is_part_of_immutable_release_identity(tmp_path):
    fixture = _conditional_fixture(tmp_path)
    policy = fixture.capital_policy
    changed = policy.model_copy(
        update={
            "limitations": (
                *policy.limitations,
                "Additional explicit limitation retained for this conditional stress example.",
            )
        }
    )
    manifest = _manifest_with(fixture.manifest, conditional_capital_policies=(changed,))
    assert manifest.manifest_digest != fixture.manifest.manifest_digest
    assert (
        _assess(fixture, manifest=manifest).output_digest
        != _assess(fixture).output_digest
    )
    altered = fixture.manifest.model_dump() | {
        "conditional_capital_policies": (changed,)
    }
    with pytest.raises(ValueError, match="manifest_digest"):
        DataReleaseManifestV1.model_validate(altered)


@pytest.mark.parametrize("binding", ["duplicate", "extra", "foreign_fact", "digest"])
def test_release_refuses_unbound_conditional_policies(tmp_path, binding):
    fixture = _conditional_fixture(tmp_path)
    policy = fixture.capital_policy
    if binding in {"duplicate", "extra"}:
        other = (
            policy
            if binding == "duplicate"
            else policy.model_copy(update={"snapshot_manifest_digest": "f" * 64})
        )
        policies = (policy, other)
    else:
        role = "cash_and_equivalents"
        old = policy.observations[role]
        ref = old.model_copy(
            update={"fact_id": "unreleased-fact"}
            if binding == "foreign_fact"
            else {"fact_digest": "f" * 64}
        )
        policies = (
            policy.model_copy(
                update={"observations": policy.observations | {role: ref}}
            ),
        )
    manifest = _manifest_with(fixture.manifest, conditional_capital_policies=policies)
    with pytest.raises(DataReleaseError) as error:
        _assess(fixture, manifest=manifest)
    assert error.value.code == "DATA_RELEASE_CONDITIONAL_CAPITAL_UNBOUND"
    fixture.manifest = manifest
    candidate, canary = _reviewed_candidate(fixture)
    with pytest.raises(DataReleaseError, match="conditional"):
        canary.validate(candidate.manifest, candidate.verification)


@pytest.mark.parametrize("mutation", ["missing", "changed", "extra"])
def test_assessor_requires_entire_released_fact_set(tmp_path, mutation):
    fixture = _conditional_fixture(tmp_path)
    facts = fixture.stored
    if mutation == "missing":
        facts = facts[1:]
    elif mutation == "changed":
        facts = (facts[0].model_copy(update={"value": Decimal("99999")}), *facts[1:])
    else:
        facts = (*facts, facts[0].model_copy(update={"fact_id": "extra"}))
    with pytest.raises(DataReleaseError) as error:
        _assess(fixture, facts=facts)
    assert error.value.code == "DATA_RELEASE_CONDITIONAL_CAPITAL_FACT_MISMATCH"


def test_conditional_policy_refuses_foreign_security_time_and_mapping(tmp_path):
    fixture = _conditional_fixture(tmp_path)
    with pytest.raises(DataReleaseError) as error:
        _assess(fixture, mapping_version="another-version")
    assert error.value.code == "CONDITIONAL_CAPITAL_MAPPING_MISMATCH"
    for updates in (
        {"security_id": "OTHER"},
        {
            "valuation_timestamp": fixture.snapshot.valuation_timestamp
            + timedelta(days=1)
        },
    ):
        policy = fixture.capital_policy.model_copy(update=updates)
        manifest = _manifest_with(
            fixture.manifest, conditional_capital_policies=(policy,)
        )
        with pytest.raises(DataReleaseError) as error:
            _assess(fixture, manifest=manifest)
        assert error.value.code == "CONDITIONAL_CAPITAL_SNAPSHOT_MISMATCH"


def test_conditional_profile_cannot_serve_another_model_or_weaken_observed_fields(
    tmp_path,
):
    fixture = _conditional_fixture(tmp_path)
    with pytest.raises(DataReleaseError) as error:
        valuation_release_requirements(fixture.manifest, "transition_fcff_dcf")
    assert error.value.code == "DATA_RELEASE_VALUATION_INPUT_POLICY_MISMATCH"
    manifest = _manifest_with(
        fixture.manifest,
        required_fields=tuple(
            field
            for field in fixture.manifest.required_fields
            if field != "noncontrolling_interests"
        ),
    )
    with pytest.raises(DataReleaseError) as error:
        valuation_release_requirements(manifest, "fcff_dcf")
    assert error.value.code == "DATA_RELEASE_VALUATION_INPUT_POLICY_MISMATCH"


def test_absent_policy_preserves_exact_manifest_bytes_and_requirements(tmp_path):
    fixture = _valuation_fixture(tmp_path)
    payload = fixture.manifest.model_dump(exclude={"manifest_digest"})
    assert "conditional_capital_policies" not in payload
    assert sha256_digest(payload) == fixture.manifest.manifest_digest
    assert _assess(fixture) is None
    assert canonical_bytes(
        DataReleaseManifestV1.model_validate_json(canonical_bytes(fixture.manifest))
    ) == canonical_bytes(fixture.manifest)
    exact = valuation_requirements_profile("fcff_dcf")
    assert set(UNRESOLVED_CAPITAL_FIELDS) <= set(exact.required_fact_fields)


def test_issuer_only_operating_release_cannot_carry_equity_policy(tmp_path):
    fixture = _conditional_fixture(tmp_path)
    payload = fixture.manifest.model_dump(
        exclude={"manifest_digest", "valuation_working_capital_policy"}
    ) | {
        "protocol": "fundamental.issuer-operating-release.v1",
        "model_id": "fcff_dcf",
        "model_version": "fcff_dcf-v2",
        "policy_id": "policy",
        "policy_version": "v1",
        "mapping_version": fixture.capital_policy.mapping_version,
        "requirements_profile_digest": "a" * 64,
    }
    with pytest.raises(ValueError, match="cannot carry conditional equity"):
        IssuerOperatingReleaseManifestV1(
            **payload, manifest_digest=sha256_digest(payload)
        )
