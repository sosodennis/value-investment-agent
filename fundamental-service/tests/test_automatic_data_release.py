"""Synthetic machine signing exercises real source, signature and canary gates."""

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fundamental_service.automatic_data_release import (
    AutomaticDataReleaseCandidateV1,
    AutomaticDataReleasePolicyV1,
    AutomaticDataReleaseRequestV1,
    AutomaticDataReleaseService,
    automatic_release_suite_digest,
)
from fundamental_service.data_releases import (
    DataReleaseContentRequestV1,
    DataReleaseError,
    DataReleaseVerifierV1,
    verify_data_release_candidate,
)
from fundamental_service.automatic_release_evidence import (
    require_automatic_release_sources,
)
from fundamental_service.issuer_operating_release import _FactReader, _SourceReader
from fundamental_service.release_runner import DataReleaseCanaryRunner
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_conditional_capital_release import _conditional_fixture
from test_issuer_operating_release import fixture, inventory
from test_preparation_runner import _reviewed_candidate


KEY = Ed25519PrivateKey.from_private_bytes(b"synthetic-auto-release".ljust(32, b"0"))
REVISION = "a" * 40


def _case(tmp_path):
    bundle, _, evidence, roots, _ = fixture(tmp_path)
    store = ArtifactStore(tmp_path / "release-evidence")
    for name, raw in evidence.values.items():
        store.put_bytes_with_receipt(name, raw)
    policy = AutomaticDataReleasePolicyV1(
        profile_id=bundle.manifest.profile_id,
        scope="issuer-operating",
        model_id=bundle.manifest.model_id,
        model_version=bundle.manifest.model_version,
        mapping_version=bundle.manifest.mapping_version,
        requirements_profile_digest=bundle.manifest.requirements_profile_digest,
        parser_version=bundle.manifest.parser_version,
        quality_profile_digest=bundle.manifest.quality_profile_digest,
        validation_profile_digest=bundle.sources[0]
        .originals[0]
        .report.validation_profile_digest,
        verifier_id="synthetic-release-machine",
        workflow_identity="synthetic/deployment/automatic-release-v1",
    )
    roots = roots.model_copy(
        update={
            "verifiers": {
                **roots.verifiers,
                policy.verifier_id: DataReleaseVerifierV1(
                    workflow_identity=policy.workflow_identity,
                    public_key_ed25519_base64=base64.b64encode(
                        KEY.public_key().public_bytes_raw()
                    ).decode(),
                    verification_suite_digest=automatic_release_suite_digest(),
                ),
            }
        }
    )
    request = AutomaticDataReleaseRequestV1(
        manifest=bundle.manifest,
        content=DataReleaseContentRequestV1(
            source_revision=REVISION,
            evidence_refs=bundle.verification.evidence_refs,
            mapping_reviews=bundle.verification.mapping_reviews,
        ),
    )
    options = dict(
        snapshots=_SourceReader(bundle),
        facts=_FactReader(bundle),
        mappings=_FactReader(bundle),
        artifacts=store,
        trust_roots=roots,
        policy=policy,
        private_key=KEY,
        source_revision=REVISION,
    )
    return bundle, store, request, options


def test_machine_signs_only_after_source_checks_and_existing_canary_accepts(tmp_path):
    bundle, store, request, options = _case(tmp_path)
    receipt = AutomaticDataReleaseService(**options).verify_and_sign(request)
    assert receipt.decision.status == "passed" and receipt.wrote
    assert receipt.decision.regulatory_evidence_digests
    candidate = AutomaticDataReleaseCandidateV1.model_validate_json(
        store.read(receipt.candidate_publication.artifact.artifact_id)
    )
    assert canonical_bytes(candidate.manifest) == canonical_bytes(bundle.manifest)
    verify_data_release_candidate(
        candidate.manifest, candidate.verification, options["trust_roots"]
    )
    canary = DataReleaseCanaryRunner(
        snapshot_repository=options["snapshots"],
        fact_repository=options["facts"],
        mapping_reader=options["mappings"],
        artifact_reader=store,
        trust_roots=options["trust_roots"],
    ).validate(candidate.manifest, candidate.verification)
    assert sha256_digest(canary) == receipt.canary_publication.artifact.content_hash
    assert not any("approval" in key for key in receipt.model_dump())


def test_identical_restart_and_concurrent_runs_reuse_candidate_and_all_evidence(
    tmp_path,
):
    _, store, request, options = _case(tmp_path)
    first = AutomaticDataReleaseService(**options).verify_and_sign(request)
    assert first.candidate_publication is not None
    before = inventory(store.root)

    def replay(_):
        service = AutomaticDataReleaseService(
            **(options | {"artifacts": ArtifactStore(store.root)})
        )
        return service.verify_and_sign(request)

    with ThreadPoolExecutor(max_workers=3) as pool:
        repeats = tuple(pool.map(replay, range(3)))
    assert inventory(store.root) == before
    for receipt in repeats:
        assert receipt.input_digest == first.input_digest
        assert receipt.output_digest == first.output_digest
        assert (
            receipt.candidate_publication.artifact
            == first.candidate_publication.artifact
        )
        assert not receipt.wrote


@pytest.mark.parametrize(
    "field,value",
    (
        ("profile_id", "different-profile"),
        ("scope", "security"),
        ("model_id", "transition_fcff_dcf"),
        ("model_version", "fcff_dcf-nonexistent"),
        ("mapping_version", "different-mapping"),
        ("requirements_profile_digest", "0" * 64),
        ("parser_version", "arelle-unknown"),
        ("quality_profile_digest", "0" * 64),
        ("validation_profile_digest", "0" * 64),
    ),
)
def test_deployment_pins_refuse_and_retain_reason_without_candidate(
    tmp_path, field, value
):
    _, store, request, options = _case(tmp_path)
    options["policy"] = options["policy"].model_copy(update={field: value})
    receipt = AutomaticDataReleaseService(**options).verify_and_sign(request)
    assert receipt.decision.status == "blocked"
    assert receipt.decision.issue_codes == (
        "AUTOMATIC_RELEASE_VALIDATION_PROFILE_MISMATCH"
        if field == "validation_profile_digest"
        else "AUTOMATIC_RELEASE_POLICY_MISMATCH",
    )
    assert receipt.candidate_publication is receipt.canary_publication is None
    assert not any(
        "automatic-release-candidate" in name for name in inventory(store.root)
    )
    assert canonical_bytes(receipt.decision) == store.read(
        receipt.decision_publication.artifact.artifact_id
    )


@pytest.mark.parametrize("fault", ("suite", "workflow", "key", "verifier", "revision"))
def test_unrelated_verifier_authority_cannot_sign_this_suite(tmp_path, fault):
    _, _, request, options = _case(tmp_path)
    policy = options["policy"]
    if fault == "key":
        options["private_key"] = Ed25519PrivateKey.generate()
    elif fault in {"workflow", "verifier"}:
        field = "workflow_identity" if fault == "workflow" else "verifier_id"
        options["policy"] = policy.model_copy(update={field: "untrusted"})
    elif fault == "revision":
        options["source_revision"] = "b" * 40
    else:
        roots = options["trust_roots"]
        verifiers = dict(roots.verifiers)
        verifiers[policy.verifier_id] = verifiers[policy.verifier_id].model_copy(
            update={"verification_suite_digest": "0" * 64}
        )
        options["trust_roots"] = roots.model_copy(update={"verifiers": verifiers})
    receipt = AutomaticDataReleaseService(**options).verify_and_sign(request)
    assert receipt.decision.issue_codes == (
        "AUTOMATIC_RELEASE_REVISION_MISMATCH"
        if fault == "revision"
        else "AUTOMATIC_RELEASE_AUTHORITY_MISMATCH",
    )
    assert receipt.candidate_publication is None


@pytest.mark.parametrize("fault", ("future", "missing", "conflict", "corrupt"))
def test_actual_content_refusals_are_persisted_and_never_signed(tmp_path, fault):
    bundle, store, request, options = _case(tmp_path)
    if fault == "future":
        facts = tuple(
            fact.model_copy(
                update={
                    "available_at": bundle.sources[0].valuation_timestamp
                    + timedelta(days=1)
                }
            )
            for fact in bundle.facts
        )
        options["facts"] = _FactReader(bundle.model_copy(update={"facts": facts}))
    elif fault == "missing":
        request = request.model_copy(
            update={
                "content": request.content.model_copy(update={"mapping_reviews": ()})
            }
        )
    elif fault == "conflict":
        ref = request.content.evidence_refs[0]
        request = request.model_copy(
            update={
                "content": request.content.model_copy(
                    update={
                        "evidence_refs": (
                            ref,
                            ref.model_copy(update={"content_hash": "0" * 64}),
                        )
                    }
                )
            }
        )
    else:
        record = store.get(bundle.manifest.artifact_refs[0].artifact_id)
        original = store._artifact_path(record.content_hash, record.media_type)
        original.write_bytes(b"corrupted")
    receipt = AutomaticDataReleaseService(**options).verify_and_sign(request)
    assert receipt.decision.status == "blocked"
    assert receipt.decision.issue_codes
    assert receipt.candidate_publication is receipt.canary_publication is None


def test_conditional_content_pass_does_not_claim_missing_sec_evidence(tmp_path):
    fixture = _conditional_fixture(tmp_path)
    candidate, runner = _reviewed_candidate(fixture)
    content_request = DataReleaseContentRequestV1(
        source_revision=candidate.verification.source_revision,
        evidence_refs=candidate.verification.evidence_refs,
        mapping_reviews=candidate.verification.mapping_reviews,
    )
    assert runner.validate_content(candidate.manifest, content_request)
    with pytest.raises(DataReleaseError) as caught:
        require_automatic_release_sources(
            candidate.manifest,
            content_request,
            snapshots=fixture.snapshots,
            mappings=fixture,
            artifacts=fixture.artifacts,
            validation_profile_digest="0" * 64,
        )
    assert caught.value.code == "AUTOMATIC_RELEASE_MAPPING_METHOD_UNSUPPORTED"


def test_interrupted_candidate_write_resumes_checked_evidence(tmp_path, monkeypatch):
    _, store, request, options = _case(tmp_path)
    put = store.put_with_receipt

    def interrupted(artifact_id, *args, **kwargs):
        if artifact_id.startswith("automatic-release-candidate-"):
            raise SnapshotError(
                "SYNTHETIC_INTERRUPTION", "simulated storage interruption"
            )
        return put(artifact_id, *args, **kwargs)

    monkeypatch.setattr(store, "put_with_receipt", interrupted)
    stopped = AutomaticDataReleaseService(**options).verify_and_sign(request)
    assert stopped.decision.issue_codes == ("SYNTHETIC_INTERRUPTION",)
    assert stopped.candidate_publication is None
    monkeypatch.setattr(store, "put_with_receipt", put)
    completed = AutomaticDataReleaseService(**options).verify_and_sign(request)
    assert completed.decision.status == "passed"
    assert completed.candidate_publication.wrote
    assert not completed.canary_publication.wrote
    before = inventory(store.root)
    replay = AutomaticDataReleaseService(**options).verify_and_sign(request)
    assert not replay.wrote and replay.output_digest == completed.output_digest
    assert inventory(store.root) == before
