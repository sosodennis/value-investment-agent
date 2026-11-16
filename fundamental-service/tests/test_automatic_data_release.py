"""Synthetic machine signing exercises real source, signature and canary gates."""

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

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
from fundamental_service.policies import (
    FilesystemPolicyRepository,
    PolicyRegistry,
    initial_model_specs,
)
from fundamental_service.release_runner import DataReleaseCanaryRunner
from fundamental_service.replay import ArtifactStore
from fundamental_service.operations import ServiceError
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_conditional_capital_release import _conditional_fixture
from test_issuer_operating_release import fixture, inventory
from test_preparation_runner import _reviewed_candidate
from market_policy_fixtures import synthetic_policy_registry
from test_automatic_market_policy_evidence import _authorization, _bound


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


@pytest.mark.parametrize("stage", ("validate_content", "validate"))
def test_expired_verification_cannot_publish_a_trusted_candidate(
    tmp_path, monkeypatch, stage
):
    import fundamental_service.operations as operations

    _, store, request, options = _case(tmp_path)
    deadline = datetime.now(UTC) + timedelta(minutes=1)
    previous = getattr(DataReleaseCanaryRunner, stage)

    def exhaust_budget(*args, **kwargs):
        result = previous(*args, **kwargs)
        monkeypatch.setattr(
            operations,
            "datetime",
            SimpleNamespace(now=lambda tz: deadline + timedelta(seconds=1)),
        )
        return result

    monkeypatch.setattr(DataReleaseCanaryRunner, stage, exhaust_budget)
    published = []
    write = store.put_with_receipt

    def record_write(artifact_id, *args, **kwargs):
        published.append(artifact_id)
        return write(artifact_id, *args, **kwargs)

    monkeypatch.setattr(store, "put_with_receipt", record_write)
    with pytest.raises(ServiceError) as error:
        AutomaticDataReleaseService(**options).verify_and_sign(
            request, deadline_at=deadline
        )
    assert error.value.code == "REQUEST_DEADLINE_EXCEEDED"
    assert not any(
        name.startswith("automatic-release-candidate-") for name in published
    )


@pytest.mark.parametrize("stage", ("canary_write", "policy_install"))
def test_expiry_during_publication_stops_subsequent_trusted_writes(
    tmp_path, monkeypatch, stage
):
    import fundamental_service.operations as operations

    _, store, request, options = _case(tmp_path / "machine")
    policy = _bound()[2]
    second_policy = _authorization(policy, policy_id="second-staged-policy")
    repository = FilesystemPolicyRepository(tmp_path / "policies")
    registry = PolicyRegistry(initial_model_specs(), repository=repository)
    options["policy_registry"] = registry
    monkeypatch.setattr(
        AutomaticDataReleaseService,
        "_market_registry",
        lambda self, request: (
            PolicyRegistry(initial_model_specs(), (policy, second_policy)),
            (policy, second_policy),
        ),
    )
    deadline = datetime.now(UTC) + timedelta(minutes=1)

    def expire():
        monkeypatch.setattr(
            operations,
            "datetime",
            SimpleNamespace(now=lambda tz: deadline + timedelta(seconds=1)),
        )

    published = []
    write = store.put_with_receipt

    def record_write(artifact_id, *args, **kwargs):
        result = write(artifact_id, *args, **kwargs)
        published.append(artifact_id)
        if stage == "canary_write" and artifact_id.startswith(
            "automatic-release-canary-"
        ):
            expire()
        return result

    install = registry.add_policy

    def install_policy(item):
        result = install(item)
        if stage == "policy_install":
            expire()
        return result

    monkeypatch.setattr(store, "put_with_receipt", record_write)
    monkeypatch.setattr(registry, "add_policy", install_policy)
    with pytest.raises(ServiceError) as error:
        AutomaticDataReleaseService(**options).verify_and_sign(
            request, deadline_at=deadline
        )
    assert error.value.code == "REQUEST_DEADLINE_EXCEEDED"
    assert repository.list() == (() if stage == "canary_write" else (policy,))
    assert not any(
        name.startswith("automatic-release-candidate-") for name in published
    )


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


def test_authorized_key_rotation_has_distinct_input_and_no_artifact_collision(tmp_path):
    _, store, request, options = _case(tmp_path)
    first = AutomaticDataReleaseService(**options).verify_and_sign(request)
    key = Ed25519PrivateKey.generate()
    policy = options["policy"]
    roots = options["trust_roots"]
    verifiers = dict(roots.verifiers)
    verifiers[policy.verifier_id] = verifiers[policy.verifier_id].model_copy(
        update={
            "public_key_ed25519_base64": base64.b64encode(
                key.public_key().public_bytes_raw()
            ).decode()
        }
    )
    rotated = options | {
        "private_key": key,
        "trust_roots": roots.model_copy(update={"verifiers": verifiers}),
    }
    second = AutomaticDataReleaseService(**rotated).verify_and_sign(request)
    assert first.decision.status == second.decision.status == "passed"
    assert first.input_digest != second.input_digest
    assert first.output_digest != second.output_digest
    assert (
        first.candidate_publication.artifact.artifact_id
        != second.candidate_publication.artifact.artifact_id
    )
    before = inventory(store.root)
    assert not AutomaticDataReleaseService(**rotated).verify_and_sign(request).wrote
    assert inventory(store.root) == before


@pytest.mark.parametrize("exception", (KeyError, FileNotFoundError))
def test_missing_mapping_adapter_retains_a_blocked_decision(tmp_path, exception):
    _, _, request, options = _case(tmp_path)

    class MissingMapping:
        def get_mapping(self, mapping_id):
            raise exception(mapping_id)

    options["mappings"] = MissingMapping()
    receipt = AutomaticDataReleaseService(**options).verify_and_sign(request)
    assert receipt.decision.issue_codes == ("DATA_RELEASE_MAPPING_UNAVAILABLE",)
    assert receipt.candidate_publication is None
    assert not AutomaticDataReleaseService(**options).verify_and_sign(request).wrote


def test_registry_load_order_preserves_full_input_and_candidate_identity(tmp_path):
    _, store, request, options = _case(tmp_path)
    registry = synthetic_policy_registry()
    first = AutomaticDataReleaseService(
        **(options | {"policy_registry": registry})
    ).verify_and_sign(request)
    before = inventory(store.root)
    reordered = PolicyRegistry(
        tuple(reversed(registry.models())), tuple(reversed(registry.policies()))
    )
    second = AutomaticDataReleaseService(
        **(options | {"policy_registry": reordered})
    ).verify_and_sign(request)
    assert first.decision.status == second.decision.status == "passed"
    assert first.input_digest == second.input_digest
    assert first.output_digest == second.output_digest
    assert not second.wrote and inventory(store.root) == before


def test_security_market_plans_must_select_the_composers_effective_model(tmp_path):
    _, store, _, options = _case(tmp_path / "machine")
    fixture = _conditional_fixture(tmp_path / "conditional")
    candidate, _ = _reviewed_candidate(fixture)
    manifest, _, policy, _, contents, _ = _bound(
        manifest=candidate.manifest, snapshot=fixture.snapshot
    )
    for artifact_id, raw in contents.items():
        store.put_bytes_with_receipt(artifact_id, raw, media_type="application/json")
    options.update(
        snapshots=fixture.snapshots,
        policy=options["policy"].model_copy(update={"scope": "security"}),
    )
    options["policy_registry"] = PolicyRegistry(initial_model_specs(), (policy,))
    assert AutomaticDataReleaseService(**options)._require_market_model(manifest) == (
        policy.policy_digest,
    )
    wrong = _authorization(
        policy, model_id="transition_fcff_dcf", model_version="transition_fcff_dcf-v2"
    )
    effective = _authorization(policy, policy_id="correct-fcff-policy")
    options["policy_registry"] = PolicyRegistry(
        initial_model_specs(), (wrong, effective)
    )
    with pytest.raises(DataReleaseError) as caught:
        AutomaticDataReleaseService(**options)._require_market_model(manifest)
    assert caught.value.code == "AUTOMATIC_RELEASE_MARKET_MODEL_MISMATCH"


@pytest.mark.parametrize("refuse_content", (False, True))
def test_staged_policy_publication_waits_for_all_release_checks_and_replays(
    tmp_path, monkeypatch, refuse_content
):
    _, store, request, options = _case(tmp_path / "machine")
    policy = _bound()[2]
    repository = FilesystemPolicyRepository(tmp_path / "policies")
    registry = PolicyRegistry(initial_model_specs(), repository=repository)
    options["policy_registry"] = registry
    # Isolate publication order from the separately tested policy authority.
    monkeypatch.setattr(
        AutomaticDataReleaseService,
        "_market_registry",
        lambda self, request: (
            PolicyRegistry(initial_model_specs(), (policy,)),
            (policy,),
        ),
    )
    if refuse_content:
        request = request.model_copy(
            update={
                "content": request.content.model_copy(update={"mapping_reviews": ()})
            }
        )
    first = AutomaticDataReleaseService(**options).verify_and_sign(request)
    if refuse_content:
        assert first.decision.status == "blocked"
        assert repository.list() == ()
        assert first.candidate_publication is first.canary_publication is None
    else:
        assert first.decision.status == "passed"
        assert repository.get(policy.policy_id) == policy
        assert first.canary_publication is not None
    before = inventory(tmp_path)
    reopened = PolicyRegistry(
        initial_model_specs(),
        repository=FilesystemPolicyRepository(tmp_path / "policies"),
    )
    repeated = AutomaticDataReleaseService(
        **(options | {"policy_registry": reopened})
    ).verify_and_sign(request)
    assert first.input_digest == repeated.input_digest
    assert first.output_digest == repeated.output_digest
    assert not repeated.wrote and inventory(tmp_path) == before
