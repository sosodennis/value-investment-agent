from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fundamental_service.app import create_app
from fundamental_service.application.service import ServiceError
from fundamental_service.contracts import ValuationEvidenceReadRequestV1
from fundamental_service.data_releases import (
    ArtifactRefV1,
    DataReleaseError,
    DataReleaseManifestV1,
    sign_data_release_verification,
)
from fundamental_service.release_runner import DataReleaseCanaryRunner
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.source_admission import admit_macro_source
from fundamental_service.damodaran_source import DamodaranReferenceProvider
from fundamental_service.source_admission_evidence import (
    SOURCE_ADMISSION_ROLE,
    SOURCE_ORIGINAL_ROLE,
    SOURCE_TERMS_ROLE,
    load_release_source_admissions,
)
from test_release_runner import _candidate
from test_preparation_runner import _fixture
from test_source_admission import (
    CAPTURE,
    METRIC,
    JsonRateProvider,
    _admit,
    _macro_inputs,
    _reference_policy,
    _source,
    _terms,
)


class DictionaryArtifacts:
    def __init__(self, data: dict[str, bytes]):
        self.data = data

    def read(self, artifact_id: str) -> bytes:
        return self.data[artifact_id]


def _packet(manifest, *, raw=None, result=None, inputs=None):
    inputs = _macro_inputs() if inputs is None else inputs
    admission = result or admit_macro_source(JsonRateProvider(), **inputs)
    data = {}
    refs = []
    for index, (role, content) in enumerate(
        (
            (SOURCE_ADMISSION_ROLE, raw or canonical_bytes(admission)),
            *((SOURCE_ORIGINAL_ROLE, x.content) for x in inputs["sources"]),
            *((SOURCE_TERMS_ROLE, x.content) for x in inputs["terms"]),
        )
    ):
        digest = hashlib.sha256(content).hexdigest()
        name = f"source-admission-{index}-{digest}"
        data[name] = content
        refs.append(
            ArtifactRefV1(
                artifact_id=name,
                content_hash=digest,
                media_type="application/json"
                if index == 0
                else "application/octet-stream",
                role=role,
            )
        )
    payload = manifest.model_dump(exclude={"manifest_digest"})
    payload["artifact_refs"] = (*manifest.artifact_refs, *refs)
    return (
        DataReleaseManifestV1(**payload, manifest_digest=sha256_digest(payload)),
        DictionaryArtifacts(data),
        admission,
        inputs,
    )


def _load(manifest, artifacts, inputs, **updates):
    kwargs = dict(
        artifacts=artifacts,
        policy=inputs["policy"],
        macro_providers=(JsonRateProvider(),),
        reference_providers=(),
    )
    kwargs.update(updates)
    return load_release_source_admissions(manifest, **kwargs)


def test_release_loader_reproduces_retained_originals_without_mutation():
    manifest = _candidate()[0]
    manifest, artifacts, admission, inputs = _packet(manifest)
    before = dict(artifacts.data)
    assert _load(manifest, artifacts, inputs) == (admission,)
    assert _load(manifest, artifacts, inputs) == (admission,)
    assert artifacts.data == before


def test_release_reference_reproduction_uses_its_own_injected_port():
    inputs = dict(
        metric=METRIC,
        sources=(_source(),),
        terms=(_terms(),),
        policy=_reference_policy(),
        valuation_at=CAPTURE,
    )
    admission = _admit()
    manifest, artifacts, _, _ = _packet(
        _candidate()[0], result=admission, inputs=inputs
    )
    assert _load(
        manifest,
        artifacts,
        inputs,
        macro_providers=(),
        reference_providers=(DamodaranReferenceProvider(),),
    ) == (admission,)
    with pytest.raises(DataReleaseError) as error:
        _load(manifest, artifacts, inputs, reference_providers=())
    assert error.value.code == "SOURCE_ADMISSION_PROVIDER_UNAVAILABLE"


def test_repeated_admission_identity_is_not_published_twice_in_a_release():
    manifest, artifacts, admission, inputs = _packet(_candidate()[0])
    original = next(
        x for x in manifest.artifact_refs if x.role == SOURCE_ADMISSION_ROLE
    )
    duplicate = original.model_copy(
        update={"artifact_id": original.artifact_id + "-duplicate"}
    )
    artifacts.data[duplicate.artifact_id] = canonical_bytes(admission)
    manifest = manifest.model_copy(
        update={"artifact_refs": (*manifest.artifact_refs, duplicate)}
    )
    with pytest.raises(DataReleaseError) as error:
        _load(manifest, artifacts, inputs)
    assert error.value.code == "SOURCE_ADMISSION_DUPLICATE"


@pytest.mark.parametrize(
    "change,code",
    [
        ("policy", "SOURCE_ADMISSION_POLICY_UNAVAILABLE"),
        ("provider", "SOURCE_ADMISSION_PROVIDER_UNAVAILABLE"),
        ("ambiguous_provider", "SOURCE_ADMISSION_PROVIDER_UNAVAILABLE"),
        ("missing_original", "SOURCE_ADMISSION_ORIGINAL_MISSING"),
        ("corrupt_original", "SOURCE_ADMISSION_ORIGINAL_MISMATCH"),
        ("corrupt_admission", "SOURCE_ADMISSION_ARTIFACT_MISMATCH"),
    ],
)
def test_release_cannot_authorize_unreproduced_source_admission(change, code):
    manifest, artifacts, _, inputs = _packet(_candidate()[0])
    updates = {}
    if change == "policy":
        updates["policy"] = None
    elif change == "provider":
        updates["macro_providers"] = ()
    elif change == "ambiguous_provider":
        updates["macro_providers"] = (JsonRateProvider(), JsonRateProvider())
    elif change == "missing_original":
        manifest = manifest.model_copy(
            update={
                "artifact_refs": tuple(
                    x for x in manifest.artifact_refs if x.role != SOURCE_ORIGINAL_ROLE
                )
            }
        )
    else:
        role = (
            SOURCE_ORIGINAL_ROLE
            if change == "corrupt_original"
            else SOURCE_ADMISSION_ROLE
        )
        ref = next(x for x in manifest.artifact_refs if x.role == role)
        artifacts.data[ref.artifact_id] = b"changed original"
    with pytest.raises(DataReleaseError) as error:
        _load(manifest, artifacts, inputs, **updates)
    assert error.value.code == code


def test_source_policy_from_a_different_catalog_is_not_trusted_by_digest_alone():
    manifest, artifacts, _, inputs = _packet(_candidate()[0])
    policy = inputs["policy"].model_copy(update={"policy_version": "other"})
    with pytest.raises(DataReleaseError) as error:
        _load(manifest, artifacts, inputs, policy=policy)
    assert error.value.code == "SOURCE_ADMISSION_REPLAY_MISMATCH"


def test_noncanonical_and_refused_declarations_do_not_enter_a_release():
    manifest = _candidate()[0]
    inputs = _macro_inputs()
    refused = admit_macro_source(
        JsonRateProvider(), **inputs, intended_use="raw_data_redistribution"
    )
    candidate, artifacts, _, _ = _packet(manifest, result=refused)
    with pytest.raises(DataReleaseError) as error:
        _load(candidate, artifacts, inputs)
    assert error.value.code == "SOURCE_ADMISSION_REFUSED"
    candidate, artifacts, _, _ = _packet(manifest, raw=canonical_bytes(refused) + b"\n")
    with pytest.raises(DataReleaseError) as error:
        _load(candidate, artifacts, inputs)
    assert error.value.code == "SOURCE_ADMISSION_NONCANONICAL"


def test_canary_runs_configured_provider_reproduction_before_activation():
    manifest, verification, snapshots, facts, mappings, seed_artifacts, roots = (
        _candidate()
    )
    manifest, artifacts, admission, inputs = _packet(manifest)
    artifacts.data["release-evidence"] = seed_artifacts.content
    payload = verification.model_dump(exclude={"verification_digest", "signature"})
    payload["manifest_digest"] = manifest.manifest_digest
    verification = sign_data_release_verification(
        payload, Ed25519PrivateKey.from_private_bytes(b"verifier-key".ljust(32, b"0"))
    )
    runner = DataReleaseCanaryRunner(
        snapshot_repository=snapshots,
        fact_repository=facts,
        mapping_reader=mappings,
        artifact_reader=artifacts,
        trust_roots=roots,
        macro_providers=(JsonRateProvider(),),
        source_use_policy=inputs["policy"],
    )
    first = runner.validate(manifest, verification)
    assert first == runner.validate(manifest, verification)
    assert (
        hashlib.sha256(canonical_bytes(admission)).hexdigest()
        in first.checked_artifact_digests
    )
    unavailable = DataReleaseCanaryRunner(
        snapshot_repository=snapshots,
        fact_repository=facts,
        mapping_reader=mappings,
        artifact_reader=artifacts,
        trust_roots=roots,
    )
    with pytest.raises(DataReleaseError) as error:
        unavailable.validate(manifest, verification)
    assert error.value.code == "SOURCE_ADMISSION_POLICY_UNAVAILABLE"


def test_serving_composition_injects_and_checks_the_same_provider_and_policy(tmp_path):
    fixture = _fixture(tmp_path)
    from quote_provider_fixtures import bind_synthetic_quote_permission

    inputs = _macro_inputs()
    inputs["policy"] = bind_synthetic_quote_permission(fixture, inputs["policy"])
    manifest, artifacts, _, inputs = _packet(fixture.manifest, inputs=inputs)
    read_existing = fixture.artifacts.read

    class CombinedArtifacts:
        def read(self, name):
            return (
                artifacts.data[name] if name in artifacts.data else read_existing(name)
            )

    fixture.metadata.get_data_release_manifest = (
        lambda digest: manifest if digest == manifest.manifest_digest else None
    )
    app = create_app(
        snapshot_repository=fixture.snapshots,
        fact_repository=fixture.facts,
        artifact_store=CombinedArtifacts(),
        metadata_store=fixture.metadata,
        config=fixture.application.config,
        policy_registry=fixture.application.policy_registry,
        macro_providers=(JsonRateProvider(),),
        reference_providers=(),
        source_use_policy=inputs["policy"],
    )
    application = app.state.application
    request = ValuationEvidenceReadRequestV1(
        contract_version="fundamental.v1",
        snapshot_id=fixture.snapshot.snapshot_id,
        data_release_manifest_digest=manifest.manifest_digest,
        model_id="fcff_dcf",
    )
    assert application.prepare_valuation(request).status == "prepared"
    assert application.source_use_policy == inputs["policy"]
    invalid = replace(application, macro_providers=())
    with pytest.raises(ServiceError) as error:
        invalid.prepare_valuation(request)
    assert error.value.code == "SOURCE_ADMISSION_PROVIDER_UNAVAILABLE"
