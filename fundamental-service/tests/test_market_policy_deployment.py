from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fundamental_service.application.service import ServiceError
from fundamental_service.contracts import (
    CallerApprovalEnvelopeV1,
    QualityStatus,
    ValuationEvidenceReadRequestV1,
)
from fundamental_service.data_releases import (
    ActiveDataReleaseV1,
    ActiveDataReleaseWithManifestV1,
    DataReleaseCandidatePublishRequestV1,
    DataReleaseError,
    sign_data_release_verification,
)
from fundamental_service.market_policy_deployment import MarketPolicyDeployment
from fundamental_service.policies import FilesystemPolicyRepository, PolicyRegistry
from fundamental_service.preparation_runner import SourcePreparationRunner, main
from fundamental_service.release_runner import DataReleaseCanaryRunner
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_automatic_market_policy_evidence import (
    _authorization,
    _service_bound,
    _service_source_policy,
)
from test_preparation_runner import (
    VALUATION_TIME,
    _fixture,
    _reader,
    _reviewed_candidate,
    _run,
)


def _deployment_fixture(tmp_path):
    fixture = _fixture(
        tmp_path, base_source_policy=_service_source_policy(VALUATION_TIME)
    )
    original, original_canary = _reviewed_candidate(fixture)
    fixture.manifest = original.manifest
    manifest, expected, application, _ = _service_bound(fixture)
    fixture.artifacts.put_bytes_with_receipt(
        "release-evidence", original_canary._artifacts.read("release-evidence")
    )
    verification = sign_data_release_verification(
        {
            **original.verification.model_dump(
                exclude={"signature", "verification_digest"}
            ),
            "manifest_digest": manifest.manifest_digest,
        },
        Ed25519PrivateKey.from_private_bytes(b"verifier-key".ljust(32, b"0")),
    )
    candidate = DataReleaseCandidatePublishRequestV1(
        manifest=manifest, verification=verification
    )
    repository = FilesystemPolicyRepository(tmp_path / "policies")
    registry = PolicyRegistry(
        fixture.application.policy_registry.models(),
        tuple(
            _authorization(item, policy_id="legacy-" + item.policy_id)
            if item.policy_id == expected.policy_id
            else item
            for item in fixture.application.policy_registry.policies()
        ),
        repository=repository,
    )
    manifests = {
        item.manifest_digest: item
        for item in (fixture.active.manifest, original.manifest, manifest)
    }
    fixture.metadata.get_data_release_manifest = manifests.get
    application = replace(
        application, policy_registry=registry, metadata_store=fixture.metadata
    )
    fixture.application = application
    kwargs = dict(
        registry=registry,
        snapshots=fixture.snapshots,
        facts=fixture.facts,
        mappings=fixture.metadata,
        artifacts=fixture.artifacts,
        trust_roots=original_canary._trust_roots,
        source_use_policy=application.source_use_policy,
        macro_providers=application.macro_providers,
        reference_providers=application.reference_providers,
        quote_providers=application.quote_providers,
        authorized_organizations=frozenset({"operators"}),
        runtime_source_revision=fixture.plan.source_revision,
    )
    deployment = MarketPolicyDeployment(policies=repository, **kwargs)
    authorization = _authorization(
        expected, market_inputs=None, data_release_manifest_digest=None
    )
    return SimpleNamespace(
        fixture=fixture,
        original=original,
        candidate=candidate,
        expected=expected,
        authorization=authorization,
        repository=repository,
        deployment=deployment,
        kwargs=kwargs,
    )


def _publish(case, **changes):
    kwargs = dict(
        authorization=case.authorization,
        authorization_digest=sha256_digest(case.authorization),
        snapshot_id=case.fixture.snapshot.snapshot_id,
        organization_id="operators",
    )
    kwargs.update(changes)
    return case.deployment.publish(case.candidate, **kwargs)


def _files(root):
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def _canary(case):
    keys = {
        "artifacts": "artifact_reader",
        "snapshots": "snapshot_repository",
        "facts": "fact_repository",
        "mappings": "mapping_reader",
        "registry": "policy_registry",
    }
    return DataReleaseCanaryRunner(
        **{
            keys.get(key, key): value
            for key, value in case.kwargs.items()
            if key not in {"authorized_organizations", "runtime_source_revision"}
        }
    )


def test_publication_is_scoped_and_reuses_after_concurrency_and_reopen(tmp_path):
    case = _deployment_fixture(tmp_path)
    fixture = case.fixture
    old_request = ValuationEvidenceReadRequestV1(
        contract_version="fundamental.v1",
        snapshot_id=fixture.snapshot.snapshot_id,
        data_release_manifest_digest=case.original.manifest.manifest_digest,
        model_id="fcff_dcf",
    )
    old_prepared = fixture.application.prepare_valuation(old_request)
    old_canary = _canary(case).validate(
        case.original.manifest, case.original.verification
    )
    old_active = fixture.state.active
    evidence, first = _publish(case)
    assert first.wrote and evidence.policy == case.expected
    assert evidence.canary.market_policy_checks
    assert fixture.state.active == old_active
    assert fixture.application.prepare_valuation(old_request) == old_prepared
    assert (
        _canary(case).validate(case.original.manifest, case.original.verification)
        == old_canary
    )
    new_request = old_request.model_copy(
        update={"data_release_manifest_digest": case.candidate.manifest.manifest_digest}
    )
    new_prepared = fixture.application.prepare_valuation(new_request)
    assert new_prepared.status == "prepared"
    assert new_prepared.input.policy_id == case.expected.policy_id
    wrong_release = new_prepared.input.model_copy(
        update={
            "valuation_context": old_prepared.input.valuation_context,
            "input_digest": None,
        }
    ).with_digest()
    with pytest.raises(ServiceError) as error:
        fixture.application.calculate_valuation(
            wrong_release, correlation_id="wrong-release"
        )
    assert error.value.code == "POLICY_DATA_RELEASE_MISMATCH"
    before = _files(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        repeated = list(pool.map(lambda _: _publish(case), range(2)))
    case.deployment = MarketPolicyDeployment(
        policies=FilesystemPolicyRepository(tmp_path / "policies"),
        **{
            **case.kwargs,
            "registry": PolicyRegistry(
                fixture.application.policy_registry.models(),
                repository=FilesystemPolicyRepository(tmp_path / "policies"),
            ),
        },
    )
    repeated.append(_publish(case))
    for value, publication in repeated:
        assert value == evidence and publication.artifact == first.artifact
        assert not publication.wrote
    assert _files(tmp_path) == before
    assert fixture.state.active == old_active


@pytest.mark.parametrize(
    "change,code",
    [
        ("organization", "DATA_RELEASE_FORBIDDEN"),
        ("authorization", "MARKET_POLICY_AUTHORIZATION_MISMATCH"),
        ("revision", "AUTOMATIC_MARKET_POLICY_REVISION_MISMATCH"),
        ("snapshot", "MARKET_POLICY_SNAPSHOT_MISMATCH"),
        ("scope", "POLICY_DATA_RELEASE_MISMATCH"),
        ("model", "MODEL_UNSUPPORTED"),
        ("provider", "SOURCE_ADMISSION_PROVIDER_UNAVAILABLE"),
        ("signature", "DATA_RELEASE_VERIFICATION_SIGNATURE_INVALID"),
        ("identity", "POLICY_IMMUTABLE"),
    ],
)
def test_refused_publication_preserves_policy_artifacts_and_active_pointer(
    tmp_path, change, code
):
    case = _deployment_fixture(tmp_path)
    kwargs = {}
    if change == "organization":
        kwargs["organization_id"] = "outsider"
    elif change == "authorization":
        kwargs["authorization_digest"] = "a" * 64
    elif change == "snapshot":
        kwargs["snapshot_id"] = "missing"
    elif change in {"scope", "model"}:
        authorization = _authorization(
            case.authorization,
            **(
                {"data_release_manifest_digest": "a" * 64}
                if change == "scope"
                else {"model_version": "unknown"}
            ),
        )
        kwargs.update(
            authorization=authorization,
            authorization_digest=sha256_digest(authorization),
        )
    elif change in {"revision", "provider"}:
        case.deployment = MarketPolicyDeployment(
            policies=case.repository,
            **{
                **case.kwargs,
                **(
                    {"runtime_source_revision": "2" * 40}
                    if change == "revision"
                    else {"reference_providers": ()}
                ),
            },
        )
    elif change == "signature":
        verification = sign_data_release_verification(
            case.candidate.verification.model_dump(
                exclude={"signature", "verification_digest"}
            ),
            Ed25519PrivateKey.from_private_bytes(b"unknown-key".ljust(32, b"0")),
        )
        case.candidate = DataReleaseCandidatePublishRequestV1(
            manifest=case.candidate.manifest, verification=verification
        )
    elif change == "identity":
        case.repository.publish(case.authorization)
    before = _files(tmp_path)
    active = case.fixture.state.active
    with pytest.raises(DataReleaseError) as error:
        _publish(case, **kwargs)
    assert error.value.code == code
    assert _files(tmp_path) == before
    assert case.fixture.state.active == active


def test_retry_completes_evidence_after_policy_publication_interruption(
    tmp_path, monkeypatch
):
    case = _deployment_fixture(tmp_path)
    put = case.fixture.artifacts.put_with_receipt
    with monkeypatch.context() as patch:
        patch.setattr(
            case.fixture.artifacts,
            "put_with_receipt",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("interrupted")),
        )
        with pytest.raises(OSError, match="interrupted"):
            _publish(case)
    assert case.repository.get(case.expected.policy_id) == case.expected
    evidence, publication = _publish(case)
    assert publication.wrote and evidence.policy == case.expected
    assert not _publish(case)[1].wrote
    assert put == case.fixture.artifacts.put_with_receipt


def test_source_runner_publishes_policy_before_activation_and_formal_preparation(
    tmp_path,
):
    case = _deployment_fixture(tmp_path)
    fixture = case.fixture

    def activate(command):
        fixture.state.active = ActiveDataReleaseWithManifestV1(
            active=ActiveDataReleaseV1(
                profile_id=case.candidate.manifest.profile_id,
                manifest_digest=case.candidate.manifest.manifest_digest,
                revision=fixture.state.active.active.revision + 1,
                activated_at=fixture.snapshot.valuation_timestamp,
            ),
            manifest=case.candidate.manifest,
        )
        return fixture.state.active.active

    fixture.metadata.compare_and_swap_data_release = activate
    runner = SourcePreparationRunner(
        application=fixture.application,
        metadata=fixture.metadata,
        acquisition=None,
        artifacts=fixture.artifacts,
        canary=_canary(case),
        market_policy_deployment=case.deployment,
    )
    kwargs = dict(
        candidate=case.candidate,
        market_policy_authorization=case.authorization,
        market_policy_authorization_digest=sha256_digest(case.authorization),
    )
    first = _run(runner, fixture.plan, **kwargs)
    report = _reader(fixture, first)
    assert report.status == "approval_required"
    assert report.preparation.input.policy_id == case.expected.policy_id
    assert report.market_policy_deployment_ref is not None
    assert report.market_policy_deployment_ref.content_hash in (
        first.artifact.dependency_hashes
    )
    before = _files(tmp_path)
    repeated = _run(runner, fixture.plan, **kwargs)
    assert repeated.artifact == first.artifact and not repeated.wrote
    assert _files(tmp_path) == before
    approval = CallerApprovalEnvelopeV1(
        input_digest=report.preparation.input.input_digest,
        decision="approved",
        caller_id="operator",
        decided_at=fixture.snapshot.valuation_timestamp,
    )
    calculated = _run(runner, fixture.plan, approval=approval, **kwargs)
    result = _reader(fixture, calculated)
    assert result.status == "calculated"
    assert result.calculation.base.per_share_value > 0
    assert result.calculation.base.quality_status is QualityStatus.PROVISIONAL
    before = _files(tmp_path)
    repeated = _run(runner, fixture.plan, approval=approval, **kwargs)
    assert repeated.artifact == calculated.artifact and not repeated.wrote
    assert _files(tmp_path) == before


@pytest.mark.parametrize("missing", ["candidate", "digest", "revision", "changed"])
def test_cli_rejects_unbound_policy_authority_before_runtime_access(
    tmp_path, capsys, missing
):
    case = _deployment_fixture(tmp_path)
    paths = {}
    for name, value in (
        ("plan", case.fixture.plan),
        ("candidate", case.candidate),
        ("market-policy-authorization", case.authorization),
    ):
        path = tmp_path / (name + ".json")
        path.write_bytes(canonical_bytes(value))
        paths[name] = str(path)
    args = ["--plan", paths["plan"], "--plan-digest", case.fixture.plan.digest]
    for name in ("candidate", "market-policy-authorization"):
        if missing != name:
            args += ["--" + name, paths[name]]
    if missing != "digest":
        args += [
            "--market-policy-authorization-digest",
            "a" * 64 if missing == "changed" else sha256_digest(case.authorization),
        ]
    if missing != "revision":
        args += ["--runtime-source-revision", case.fixture.plan.source_revision]
    before = _files(tmp_path)
    assert main([*args, "--actor", "operator", "--organization", "operators"]) == 2
    assert "source preparation failed" in capsys.readouterr().err
    assert _files(tmp_path) == before
