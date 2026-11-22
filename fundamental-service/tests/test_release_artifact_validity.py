"""Retained bytes do not authorize the use of withdrawn release evidence."""

from types import SimpleNamespace

import pytest

from fundamental_service.contracts import ValuationEvidenceReadRequestV1
from fundamental_service.data_releases import DataReleaseError
from fundamental_service.operations import ServiceError
from fundamental_service.artifact_evidence import read_retained_artifact
from fundamental_service.quote_admission import (
    EQUITY_QUOTE_SOURCE_ROLE,
    QUOTE_ADMISSION_ROLE,
    QUOTE_TERMS_ROLE,
)
from fundamental_service.testsupport import auth_headers, make_internal_envelope
from test_conditional_reinvestment_composer import _prepared
from test_market_policy_deployment import _deployment_fixture, _canary


def _case(tmp_path):
    fixture, client, candidate, prepared = _prepared(tmp_path)
    request = {
        "preparation": ValuationEvidenceReadRequestV1(
            contract_version="fundamental.v1",
            snapshot_id=fixture.snapshot.snapshot_id,
            data_release_manifest_digest=candidate.manifest.manifest_digest,
            model_id="fcff_dcf",
        ).model_dump(mode="json"),
        "input": prepared.input,
    }
    return fixture, client, candidate, request


def _execute(client, request):
    artifacts = client.app.state.application.artifact_store
    before = {
        path.name: path.read_bytes()
        for path in artifacts.root.iterdir()
        if path.is_file()
    }
    response = client.post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=make_internal_envelope(request["input"].model_dump(mode="json")),
    )
    assert response.status_code >= 400, response.text
    assert {
        path.name: path.read_bytes()
        for path in artifacts.root.iterdir()
        if path.is_file()
    } == before
    return response


@pytest.mark.parametrize(
    "changes",
    (
        {"status": "stale"},
        {"status": "invalidated"},
        {"retention": "operational_cache"},
        {"artifact_id": "substituted"},
        {"content_hash": "0" * 64},
        {"media_type": "text/plain"},
    ),
)
def test_release_evidence_requires_exact_current_metadata(tmp_path, changes):
    fixture, _, _, request = _case(tmp_path)
    manifest = fixture.metadata.get_data_release_manifest(
        request["preparation"]["data_release_manifest_digest"]
    )
    ref = next(
        item for item in manifest.artifact_refs if item.role == QUOTE_ADMISSION_ROLE
    )
    record = fixture.artifacts.get(ref.artifact_id).model_copy(update=changes)
    reader = SimpleNamespace(get=lambda _: record, read=fixture.artifacts.read)
    with pytest.raises(DataReleaseError) as error:
        read_retained_artifact(reader, ref)
    assert error.value.code == "ARTIFACT_EVIDENCE_INVALID"


def test_release_evidence_rejects_invalidation_during_read(tmp_path):
    fixture, _, _, request = _case(tmp_path)
    manifest = fixture.metadata.get_data_release_manifest(
        request["preparation"]["data_release_manifest_digest"]
    )
    ref = next(
        item for item in manifest.artifact_refs if item.role == QUOTE_ADMISSION_ROLE
    )

    def withdraw(artifact_id):
        raw = fixture.artifacts.read(artifact_id)
        fixture.artifacts.invalidate(artifact_id)
        return raw

    reader = SimpleNamespace(get=fixture.artifacts.get, read=withdraw)
    with pytest.raises(DataReleaseError) as error:
        read_retained_artifact(reader, ref)
    assert error.value.code == "ARTIFACT_EVIDENCE_CHANGED"


@pytest.mark.parametrize(
    "role", (EQUITY_QUOTE_SOURCE_ROLE, QUOTE_ADMISSION_ROLE, QUOTE_TERMS_ROLE)
)
def test_calculation_rejects_withdrawn_quote_bytes(tmp_path, role):
    fixture, client, _, request = _case(tmp_path)
    manifest = fixture.metadata.get_data_release_manifest(
        request["preparation"]["data_release_manifest_digest"]
    )
    ref = next(item for item in manifest.artifact_refs if item.role == role)
    retained = fixture.artifacts.read(ref.artifact_id)
    fixture.artifacts.invalidate(ref.artifact_id)
    assert fixture.artifacts.read(ref.artifact_id) == retained
    response = _execute(client, request)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "ARTIFACT_EVIDENCE_INVALID"


@pytest.mark.parametrize(
    "dependency", ("taxonomy", "original", "verification", "mapping")
)
def test_calculation_rejects_withdrawn_release_dependencies(tmp_path, dependency):
    fixture, client, _, request = _case(tmp_path)
    digest = request["preparation"]["data_release_manifest_digest"]
    manifest = fixture.metadata.get_data_release_manifest(digest)
    verification = fixture.metadata.get_data_release_verification(digest)
    ref = (
        manifest.taxonomy_refs[0]
        if dependency == "taxonomy"
        else manifest.artifact_refs[0]
        if dependency == "original"
        else verification.evidence_refs[0]
        if dependency == "verification"
        else verification.mapping_reviews[0].evidence_refs[0]
    )
    # Use a distinct retained artifact for each dependency class. The seed
    # canary shares one fixture artifact across several references.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fundamental_service.data_releases import (
        DataReleaseManifestV1,
        sign_data_release_verification,
        sign_mapping_review_evidence,
    )
    from fundamental_service.serialization import sha256_digest

    separate = ref.model_copy(update={"artifact_id": "withdraw-" + dependency})
    fixture.artifacts.put_bytes_with_receipt(
        separate.artifact_id,
        fixture.artifacts.read(ref.artifact_id),
        media_type=ref.media_type,
    )
    manifest_payload = manifest.model_dump(exclude={"manifest_digest"})
    if dependency in {"taxonomy", "original"}:
        field = "taxonomy_refs" if dependency == "taxonomy" else "artifact_refs"
        manifest_payload[field] = tuple(
            separate if item == ref else item for item in getattr(manifest, field)
        )
    manifest = DataReleaseManifestV1(
        **manifest_payload, manifest_digest=sha256_digest(manifest_payload)
    )
    verification_payload = verification.model_dump(
        exclude={"signature", "verification_digest"}
    )
    verification_payload["manifest_digest"] = manifest.manifest_digest
    if dependency == "verification":
        verification_payload["evidence_refs"] = tuple(
            separate if item == ref else item for item in verification.evidence_refs
        )
    elif dependency == "mapping":
        reviews = list(verification.mapping_reviews)
        review = reviews[0].model_dump(exclude={"signature"})
        review["evidence_refs"] = tuple(
            separate if item == ref else item for item in reviews[0].evidence_refs
        )
        reviews[0] = sign_mapping_review_evidence(
            review,
            Ed25519PrivateKey.from_private_bytes(b"reviewer-key".ljust(32, b"0")),
        )
        verification_payload["mapping_reviews"] = tuple(reviews)
    verification = sign_data_release_verification(
        verification_payload,
        Ed25519PrivateKey.from_private_bytes(b"verifier-key".ljust(32, b"0")),
    )
    fixture.metadata.get_data_release_manifest = (
        lambda digest: manifest if digest == manifest.manifest_digest else None
    )
    fixture.metadata.get_data_release_verification = (
        lambda digest: verification if digest == manifest.manifest_digest else None
    )
    request["preparation"]["data_release_manifest_digest"] = manifest.manifest_digest
    prepared = client.app.state.application.prepare_valuation(
        ValuationEvidenceReadRequestV1.model_validate(request["preparation"])
    )
    assert prepared.status == "prepared"
    request["input"] = prepared.input
    ref = separate
    retained = fixture.artifacts.read(ref.artifact_id)
    fixture.artifacts.invalidate(ref.artifact_id)
    assert fixture.artifacts.read(ref.artifact_id) == retained
    response = _execute(client, request)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "ARTIFACT_EVIDENCE_INVALID"


@pytest.mark.parametrize("batch", (False, True))
@pytest.mark.parametrize(
    "mutation",
    (
        "invalidated",
        "stale",
        "retention",
        "dependencies",
        "dependency_race",
        "corrupt",
        "missing",
    ),
)
def test_calculation_checks_shared_report_referenced_by_mapping_input(
    tmp_path, batch, mutation
):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fundamental_service.data_releases import (
        ArtifactRefV1,
        sign_data_release_verification,
    )
    from fundamental_service.mapping_input_storage import publish_mapping_input
    from test_automatic_mapping import case

    fixture, client, _, request = _case(tmp_path / "valuation")
    mapping, _, _, _ = case(tmp_path / "mapping")
    report, envelope = publish_mapping_input(
        mapping,
        mapping.original,
        artifacts=fixture.artifacts,
        evidence_refs=mapping.evidence_refs,
        batch=batch,
    )
    digest = request["preparation"]["data_release_manifest_digest"]
    verification = fixture.metadata.get_data_release_verification(digest)
    payload = verification.model_dump(exclude={"signature", "verification_digest"})
    payload["evidence_refs"] = (
        *verification.evidence_refs,
        ArtifactRefV1(
            artifact_id=envelope.artifact.artifact_id,
            content_hash=envelope.artifact.content_hash,
            media_type=envelope.artifact.media_type,
            role="retained-mapping-envelope",
        ),
        ArtifactRefV1(
            artifact_id=envelope.artifact.artifact_id,
            content_hash=envelope.artifact.content_hash,
            media_type=envelope.artifact.media_type,
            role=(
                "automatic-mapping-batch-input-v1"
                if batch
                else "automatic-mapping-input-v1"
            ),
        ),
    )
    verification = sign_data_release_verification(
        payload,
        Ed25519PrivateKey.from_private_bytes(b"verifier-key".ljust(32, b"0")),
    )
    fixture.metadata.get_data_release_verification = lambda _: verification
    original_read = fixture.artifacts.read
    report_reads = []

    def observed(artifact_id):
        if artifact_id == report.artifact.artifact_id:
            report_reads.append(artifact_id)
        return original_read(artifact_id)

    fixture.artifacts.read = observed
    prepared = client.app.state.application.prepare_valuation(
        ValuationEvidenceReadRequestV1.model_validate(request["preparation"])
    )
    assert prepared.status == "prepared"
    assert len(report_reads) == 1
    assert report.artifact.artifact_id not in {
        ref.artifact_id for ref in verification.evidence_refs
    }
    if mutation == "corrupt":
        observed_read = fixture.artifacts.read
        fixture.artifacts.read = lambda artifact_id: (
            b"corrupt"
            if artifact_id == report.artifact.artifact_id
            else observed_read(artifact_id)
        )
    elif mutation == "invalidated":
        fixture.artifacts.invalidate(report.artifact.artifact_id)
    elif mutation == "missing":
        from fundamental_service.snapshots import SnapshotError

        get = fixture.artifacts.get

        def missing(artifact_id):
            if artifact_id == report.artifact.artifact_id:
                raise SnapshotError("ARTIFACT_NOT_FOUND", "report is unavailable")
            return get(artifact_id)

        fixture.artifacts.get = missing
    elif mutation == "dependency_race":
        get = fixture.artifacts.get
        observed_records = []

        def substitute(artifact_id):
            record = get(artifact_id)
            if artifact_id == report.artifact.artifact_id:
                observed_records.append(record)
                if len(observed_records) > 1:
                    return record.model_copy(update={"dependency_hashes": ("0" * 64,)})
            return record

        fixture.artifacts.get = substitute
    else:
        get = fixture.artifacts.get
        changes = (
            {"status": "stale"}
            if mutation == "stale"
            else {"retention": "operational_cache"}
            if mutation == "retention"
            else {"dependency_hashes": ("0" * 64,)}
        )
        fixture.artifacts.get = lambda artifact_id: (
            get(artifact_id).model_copy(update=changes)
            if artifact_id == report.artifact.artifact_id
            else get(artifact_id)
        )
    response = _execute(client, request)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == (
        "DATA_RELEASE_ARTIFACT_HASH_MISMATCH"
        if mutation == "corrupt"
        else "DATA_RELEASE_ARTIFACT_UNAVAILABLE"
        if mutation == "missing"
        else "ARTIFACT_EVIDENCE_CHANGED"
        if mutation == "dependency_race"
        else "ARTIFACT_EVIDENCE_INVALID"
    )


@pytest.mark.parametrize(
    "role",
    (
        "market_source_admission",
        "market_source_original",
        "market_source_terms",
        "issuer_market_reference_plan",
        "issuer_terminal_growth_plan",
        "automatic_market_policy_decision",
    ),
)
def test_serving_and_canary_reject_withdrawn_market_evidence(tmp_path, role):
    case = _deployment_fixture(tmp_path)
    fixture = case.fixture
    request = ValuationEvidenceReadRequestV1(
        contract_version="fundamental.v1",
        snapshot_id=fixture.snapshot.snapshot_id,
        data_release_manifest_digest=case.candidate.manifest.manifest_digest,
        model_id="fcff_dcf",
    )
    # Install the checked policy before withdrawing a release dependency.
    from test_market_policy_deployment import _publish

    _publish(case)
    assert fixture.application.prepare_valuation(request).status == "prepared"
    ref = next(
        item for item in case.candidate.manifest.artifact_refs if item.role == role
    )
    retained = fixture.artifacts.read(ref.artifact_id)
    fixture.artifacts.invalidate(ref.artifact_id)
    assert fixture.artifacts.read(ref.artifact_id) == retained
    with pytest.raises(ServiceError) as serving:
        fixture.application.prepare_valuation(request)
    assert serving.value.code == "ARTIFACT_EVIDENCE_INVALID"
    with pytest.raises(DataReleaseError):
        _canary(case).validate(case.candidate.manifest, case.candidate.verification)
