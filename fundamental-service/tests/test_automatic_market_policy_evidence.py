import hashlib

import pytest

from fundamental_service.automatic_market_policy_evidence import (
    AUTOMATIC_MARKET_POLICY_REF_PREFIX,
    AUTOMATIC_MARKET_POLICY_ROLE,
    build_automatic_market_policy_evidence,
    load_release_automatic_market_policy,
)
from fundamental_service.data_releases import ArtifactRefV1, DataReleaseError
from fundamental_service.policies import PolicyRecordV1
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_automatic_market_policy import AT, _admissions, _market_policy, _plan_decision
from test_release_runner import _candidate


class _Artifacts:
    def __init__(self, data):
        self.data = data

    def read(self, artifact_id):
        return self.data[artifact_id]


def _bound():
    manifest, _, snapshots, _, _, _, _ = _candidate()
    snapshot = snapshots.snapshot.model_copy(
        update={
            "identity": snapshots.snapshot.identity.model_copy(
                update={"issuer_id": "0000320193"}
            ),
            "valuation_timestamp": AT,
        }
    )
    plan_decision = _plan_decision(AT)
    policy_spec = _market_policy(AT)
    admissions = _admissions(AT)
    evidence = build_automatic_market_policy_evidence(
        source_revision="a" * 40,
        plan_decision=plan_decision,
        policy=policy_spec,
        admissions=admissions,
    )
    contents = {}
    refs = list(manifest.artifact_refs)
    for role, value in (
        ("issuer_market_reference_plan", plan_decision.plan),
        ("issuer_terminal_growth_plan", policy_spec.terminal_growth_plan),
        (AUTOMATIC_MARKET_POLICY_ROLE, evidence),
    ):
        raw = canonical_bytes(value)
        digest = hashlib.sha256(raw).hexdigest()
        artifact_id = f"{role}:{digest}"
        contents[artifact_id] = raw
        refs.append(
            ArtifactRefV1(
                artifact_id=artifact_id,
                content_hash=digest,
                media_type="application/json",
                role=role,
            )
        )
    manifest = manifest.model_copy(
        update={
            "artifact_refs": tuple(refs),
        }
    )
    market_policy = evidence.decision.inputs
    assert market_policy is not None
    payload = {
        "contract_version": "fundamental.v1",
        "policy_id": plan_decision.plan.policy_id,
        "policy_version": policy_spec.policy_version,
        "profile_id": "us-gaap-public-v1",
        "model_id": "fcff_dcf",
        "model_version": "fcff_dcf-v2",
        "issuer_id": "0000320193",
        "assumptions": None,
        "market_inputs": market_policy,
        "source_refs": (
            AUTOMATIC_MARKET_POLICY_REF_PREFIX
            + hashlib.sha256(canonical_bytes(evidence)).hexdigest(),
        ),
        "effective_at": AT,
        "status": "active",
    }
    policy = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    return manifest, snapshot, policy, admissions, contents, evidence


def test_release_boundary_reproduces_automatic_policy_with_injected_sources():
    manifest, snapshot, policy, admissions, contents, expected = _bound()
    result = load_release_automatic_market_policy(
        manifest,
        snapshot=snapshot,
        policy=policy,
        admissions=admissions,
        artifacts=_Artifacts(contents),
    )
    assert result == expected


def test_release_boundary_retains_missing_or_changed_automatic_evidence():
    manifest, snapshot, policy, admissions, contents, _ = _bound()
    ref = next(
        x for x in manifest.artifact_refs if x.role == AUTOMATIC_MARKET_POLICY_ROLE
    )
    missing = manifest.model_copy(
        update={"artifact_refs": tuple(x for x in manifest.artifact_refs if x != ref)}
    )
    with pytest.raises(DataReleaseError) as error:
        load_release_automatic_market_policy(
            missing,
            snapshot=snapshot,
            policy=policy,
            admissions=admissions,
            artifacts=_Artifacts(contents),
        )
    assert error.value.code == "AUTOMATIC_MARKET_POLICY_EVIDENCE_MISSING"
    contents[ref.artifact_id] = contents[ref.artifact_id] + b" "
    with pytest.raises(DataReleaseError) as error:
        load_release_automatic_market_policy(
            manifest,
            snapshot=snapshot,
            policy=policy,
            admissions=admissions,
            artifacts=_Artifacts(contents),
        )
    assert error.value.code == "AUTOMATIC_MARKET_POLICY_EVIDENCE_MISMATCH"
