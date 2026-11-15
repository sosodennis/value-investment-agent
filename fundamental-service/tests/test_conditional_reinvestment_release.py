"""Forward hypotheses require retained documents and exact release source views."""

import hashlib
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fundamental_service.conditional_reinvestment import (
    bind_conditional_reinvestment_recipe,
)
from fundamental_service.conditional_reinvestment_contracts import REINVESTMENT_UNKNOWNS
from fundamental_service.conditional_reinvestment_release import (
    REINVESTMENT_ASSUMPTION_ROLE,
    reinvestment_assumption_document,
    valuation_release_conditional_reinvestment,
)
from fundamental_service.contracts import CanonicalFactV1, PeriodType
from fundamental_service.data_releases import (
    ArtifactRefV1,
    DataReleaseError,
    DataReleaseManifestV1,
    IssuerOperatingReleaseManifestV1,
    MappingRefV1,
    sign_data_release_verification,
    sign_mapping_review_evidence,
)
from fundamental_service.facts import (
    CanonicalMappingV1,
    FilesystemCanonicalFactRepository,
)
from fundamental_service.release_runner import (
    DataReleaseCanaryRunner,
    DataReleaseCanaryReportV1,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import FilesystemSnapshotRepository
from fundamental_service.valuation_preparation import (
    compose_conditional_operating_forecasts,
)
from fundamental_service.valuation_release_inputs import valuation_release_requirements
from fundamental_service.valuation_requirements import (
    conditional_reinvestment_requirements_profile,
    valuation_requirements_profile,
)
from test_api import _release_manifest_for
from test_conditional_operating_forecast import _operating_case
from test_release_runner import _candidate
from test_valuation_release_inputs import _manifest_with


def _fixture(tmp_path):
    recipe, core, snapshot = _operating_case()
    document = reinvestment_assumption_document(recipe)
    artifacts = ArtifactStore(tmp_path / "artifacts")
    ref = artifacts.put_bytes_with_receipt(
        "forward-assumptions", document, media_type="application/json"
    ).artifact
    recipe = recipe.model_copy(
        update={
            "assumption_document_uri": f"artifact://{ref.artifact_id}",
            "assumption_document_digest": ref.content_hash,
        }
    )
    profile = conditional_reinvestment_requirements_profile(recipe.model_id)
    balances = []
    for role in profile.point_in_time_fact_fields:
        payload = core[-1].model_dump() | {
            "fact_id": role,
            "normalized_field": role,
            "concept": f"us-gaap:{role}",
            "mapping_decision_id": f"mapping-{role}",
            "value": Decimal("100"),
            "period_start": None,
            "instant": core[-1].period_end,
        }
        payload["context"].update(
            concept_qname=payload["concept"],
            period_type=PeriodType.INSTANT,
            start_date=None,
            end_date=None,
            instant=core[-1].period_end,
        )
        if role == "common_shares_outstanding":
            payload.update(unit="shares", currency=None)
            payload["context"]["unit_qname"] = "shares"
        balances.append(CanonicalFactV1.model_validate(payload))
    facts = tuple(
        fact.model_copy(update={"mapping_confidence": "high"})
        for fact in (*core, *balances)
    )
    policy = bind_conditional_reinvestment_recipe(
        recipe, facts, snapshot=snapshot
    ).policy
    manifest = _manifest_with(
        _release_manifest_for(snapshot, facts),
        required_fields=profile.required_fact_fields,
        conditional_reinvestment_policies=(policy,),
        artifact_refs=(
            ArtifactRefV1(
                artifact_id=ref.artifact_id,
                content_hash=ref.content_hash,
                media_type=ref.media_type,
                role=REINVESTMENT_ASSUMPTION_ROLE,
            ),
        ),
    )
    return SimpleNamespace(
        recipe=recipe,
        policy=policy,
        facts=facts,
        snapshot=snapshot,
        manifest=manifest,
        artifacts=artifacts,
        document=document,
    )


def _assess(
    fixture,
    *,
    manifest=None,
    facts=None,
    snapshot=None,
    mapping_version=None,
    artifacts=None,
):
    return valuation_release_conditional_reinvestment(
        manifest or fixture.manifest,
        snapshot or fixture.snapshot,
        facts if facts is not None else fixture.facts,
        mapping_version=mapping_version or fixture.recipe.mapping_version,
        artifacts=artifacts or fixture.artifacts,
    )


def _canary(fixture, tmp_path):
    seed, verification, _, _, _, seed_artifacts, roots = _candidate()
    snapshots = FilesystemSnapshotRepository(tmp_path / "snapshots")
    snapshots.publish(fixture.snapshot)
    facts = FilesystemCanonicalFactRepository(tmp_path / "facts")
    mappings = {}
    for fact in fixture.facts:
        facts.publish(fact)
        mappings[fact.mapping_decision_id] = CanonicalMappingV1(
            contract_version="fundamental.v1",
            decision_id=fact.mapping_decision_id,
            source_concept=fact.concept,
            normalized_field=fact.normalized_field,
            mapping_version=fixture.recipe.mapping_version,
            confidence=fact.mapping_confidence,
            reviewer="synthetic-contract-reviewer",
            status="approved",
        )
    manifest = _manifest_with(
        fixture.manifest,
        taxonomy_refs=seed.taxonomy_refs,
        artifact_refs=(*seed.artifact_refs, *fixture.manifest.artifact_refs),
        mapping_refs=tuple(
            MappingRefV1(mapping_id=key, mapping_digest=sha256_digest(value))
            for key, value in sorted(mappings.items())
        ),
    )
    review_payload = verification.mapping_reviews[0].model_dump(exclude={"signature"})
    verification = sign_data_release_verification(
        verification.model_dump(exclude={"signature", "verification_digest"})
        | {
            "manifest_digest": manifest.manifest_digest,
            "mapping_reviews": tuple(
                sign_mapping_review_evidence(
                    review_payload
                    | {
                        "mapping_id": ref.mapping_id,
                        "mapping_digest": ref.mapping_digest,
                    },
                    Ed25519PrivateKey.from_private_bytes(
                        b"reviewer-key".ljust(32, b"0")
                    ),
                )
                for ref in manifest.mapping_refs
            ),
        },
        Ed25519PrivateKey.from_private_bytes(b"verifier-key".ljust(32, b"0")),
    )
    artifacts = SimpleNamespace(
        read=lambda artifact_id: (
            seed_artifacts.read(artifact_id)
            if artifact_id == "release-evidence"
            else fixture.artifacts.read(artifact_id)
        )
    )
    canary = DataReleaseCanaryRunner(
        snapshot_repository=snapshots,
        fact_repository=facts,
        mapping_reader=SimpleNamespace(get_mapping=mappings.__getitem__),
        artifact_reader=artifacts,
        trust_roots=roots,
    )
    return canary, manifest, verification


def test_release_and_canary_reproduce_exact_operating_output(tmp_path):
    fixture = _fixture(tmp_path)
    first = _assess(fixture)
    assert first == _assess(fixture, facts=tuple(reversed(fixture.facts)))
    assert first.policy.unknowns == REINVESTMENT_UNKNOWNS
    assert first.supported_history_threshold is None
    assert valuation_release_requirements(fixture.manifest, "fcff_dcf") == (
        conditional_reinvestment_requirements_profile("fcff_dcf")
    )
    expected = compose_conditional_operating_forecasts(
        first.policy,
        fixture.facts,
        snapshot=fixture.snapshot,
        mapping_version=fixture.recipe.mapping_version,
    )
    canary, manifest, verification = _canary(fixture, tmp_path)
    report = canary.validate(manifest, verification)
    assert report == canary.validate(manifest, verification)
    assert report.checked_operating_forecast_digests == (expected.output_digest,)
    assert (
        DataReleaseCanaryReportV1.model_validate_json(canonical_bytes(report)) == report
    )
    with pytest.raises(ValueError, match="canary_digest"):
        DataReleaseCanaryReportV1.model_validate(
            report.model_dump()
            | {
                "checked_operating_forecast_digests": ("0" * 64,),
            }
        )


@pytest.mark.parametrize("mutation", ("missing", "changed", "extra", "duplicate"))
def test_release_requires_the_entire_declared_fact_set(tmp_path, mutation):
    fixture = _fixture(tmp_path)
    facts = fixture.facts
    if mutation == "missing":
        facts = facts[:-1]
    elif mutation == "changed":
        facts = (*facts[:-1], facts[-1].model_copy(update={"value": Decimal("9999")}))
    elif mutation == "extra":
        facts = (*facts, facts[-1].model_copy(update={"fact_id": "unreleased"}))
    else:
        facts = (*facts, facts[-1])
    with pytest.raises(DataReleaseError) as caught:
        _assess(fixture, facts=facts)
    assert caught.value.code == "DATA_RELEASE_REINVESTMENT_FACT_MISMATCH"


@pytest.mark.parametrize(
    "mutation", ("duplicate", "extra_snapshot", "foreign_fact", "digest")
)
def test_snapshot_and_observation_coverage_cannot_be_substituted(tmp_path, mutation):
    fixture = _fixture(tmp_path)
    policy = fixture.policy
    if mutation == "duplicate":
        policies = (policy, policy)
    elif mutation == "extra_snapshot":
        policies = (
            policy,
            policy.model_copy(update={"snapshot_manifest_digest": "f" * 64}),
        )
    else:
        old = policy.observations[0]
        ref = old.model_copy(
            update={"fact_id": "foreign"}
            if mutation == "foreign_fact"
            else {"fact_digest": "f" * 64}
        )
        policies = (
            policy.model_copy(update={"observations": (ref, *policy.observations[1:])}),
        )
    manifest = _manifest_with(
        fixture.manifest, conditional_reinvestment_policies=policies
    )
    with pytest.raises(DataReleaseError) as caught:
        _assess(fixture, manifest=manifest)
    assert caught.value.code == "DATA_RELEASE_REINVESTMENT_UNBOUND"


@pytest.mark.parametrize(
    "changes",
    (
        {"artifact_id": "foreign"},
        {"role": "candidate-not-approved"},
        {"content_hash": "0" * 64},
        {"media_type": "text/plain"},
    ),
)
def test_document_identity_role_type_and_hash_are_required(tmp_path, changes):
    fixture = _fixture(tmp_path)
    ref = fixture.manifest.artifact_refs[0].model_copy(update=changes)
    manifest = _manifest_with(fixture.manifest, artifact_refs=(ref,))
    with pytest.raises(DataReleaseError) as caught:
        _assess(fixture, manifest=manifest)
    assert caught.value.code == "DATA_RELEASE_REINVESTMENT_DOCUMENT_UNBOUND"


def test_document_reference_alone_cannot_prove_bytes_or_assumptions(tmp_path):
    fixture = _fixture(tmp_path)
    with pytest.raises(DataReleaseError) as caught:
        _assess(fixture, artifacts=ArtifactStore(tmp_path / "empty"))
    assert caught.value.code == "DATA_RELEASE_REINVESTMENT_DOCUMENT_UNAVAILABLE"
    with pytest.raises(DataReleaseError) as caught:
        _assess(fixture, artifacts=SimpleNamespace(read=lambda _: b"corrupt"))
    assert caught.value.code == "DATA_RELEASE_REINVESTMENT_DOCUMENT_HASH_MISMATCH"
    other = b'{"protocol":"conditional-reinvestment-assumptions-v1","claim":"precise"}'
    digest = hashlib.sha256(other).hexdigest()
    recipe = fixture.recipe.model_copy(update={"assumption_document_digest": digest})
    policy = fixture.policy.model_copy(update={"recipe": recipe})
    ref = fixture.manifest.artifact_refs[0].model_copy(update={"content_hash": digest})
    manifest = _manifest_with(
        fixture.manifest,
        artifact_refs=(ref,),
        conditional_reinvestment_policies=(policy,),
    )
    with pytest.raises(DataReleaseError) as caught:
        _assess(
            fixture, manifest=manifest, artifacts=SimpleNamespace(read=lambda _: other)
        )
    assert caught.value.code == "DATA_RELEASE_REINVESTMENT_DOCUMENT_MISMATCH"


def test_profile_retains_observed_balances_and_cannot_weaken_or_change_model(tmp_path):
    fixture = _fixture(tmp_path)
    profile = valuation_release_requirements(fixture.manifest, "fcff_dcf")
    assert profile.supported_history_threshold is None
    assert "noncontrolling_interests" in profile.required_fact_fields
    assert {"capital_expenditure", "depreciation_and_amortization", "inventory"} <= set(
        profile.supporting_fact_fields
    )
    manifest = _manifest_with(
        fixture.manifest,
        required_fields=tuple(
            field
            for field in fixture.manifest.required_fields
            if field != "noncontrolling_interests"
        ),
    )
    with pytest.raises(DataReleaseError) as caught:
        valuation_release_requirements(manifest, "fcff_dcf")
    assert caught.value.code == "DATA_RELEASE_VALUATION_INPUT_POLICY_MISMATCH"
    with pytest.raises(DataReleaseError) as caught:
        valuation_release_requirements(fixture.manifest, "transition_fcff_dcf")
    assert caught.value.code == "DATA_RELEASE_REINVESTMENT_MODEL_MISMATCH"
    with pytest.raises(DataReleaseError) as caught:
        _assess(fixture, mapping_version="other-mapping")
    assert caught.value.code == "CONDITIONAL_REINVESTMENT_MAPPING_MISMATCH"


@pytest.mark.parametrize("binding", ("issuer", "security", "date", "executable"))
def test_retained_policy_cannot_be_reused_for_a_different_context(tmp_path, binding):
    fixture = _fixture(tmp_path)
    updates = {
        "issuer": {"issuer_id": "0000000009"},
        "security": {"security_id": "another-class"},
        "date": {
            "valuation_timestamp": fixture.snapshot.valuation_timestamp
            + timedelta(days=1)
        },
        "executable": {"policy_digest": "0" * 64},
    }[binding]
    manifest = _manifest_with(
        fixture.manifest,
        conditional_reinvestment_policies=(fixture.policy.model_copy(update=updates),),
    )
    assert manifest.manifest_digest != fixture.manifest.manifest_digest
    with pytest.raises(DataReleaseError) as caught:
        _assess(fixture, manifest=manifest)
    assert caught.value.code == (
        "CONDITIONAL_REINVESTMENT_POLICY_MISMATCH"
        if binding == "executable"
        else "CONDITIONAL_REINVESTMENT_SNAPSHOT_MISMATCH"
    )


def test_old_manifest_identity_and_exact_requirements_are_preserved(tmp_path):
    fixture = _fixture(tmp_path)
    old = _release_manifest_for(fixture.snapshot, fixture.facts)
    assert "conditional_reinvestment_policies" not in old.model_dump()
    assert DataReleaseManifestV1.model_validate_json(canonical_bytes(old)) == old
    assert _assess(fixture, manifest=old) is None
    assert valuation_release_requirements(
        old, "fcff_dcf"
    ) == valuation_requirements_profile("fcff_dcf")


def test_issuer_only_release_cannot_claim_conditional_valuation_authority(tmp_path):
    fixture = _fixture(tmp_path)
    payload = fixture.manifest.model_dump(exclude={"manifest_digest"}) | {
        "protocol": "fundamental.issuer-operating-release.v1",
        "model_id": "fcff_dcf",
        "model_version": "fcff_dcf-v2",
        "policy_id": "policy",
        "policy_version": "v1",
        "mapping_version": fixture.recipe.mapping_version,
        "requirements_profile_digest": "a" * 64,
    }
    with pytest.raises(ValueError, match="cannot carry conditional valuation"):
        IssuerOperatingReleaseManifestV1(
            **payload, manifest_digest=sha256_digest(payload)
        )
