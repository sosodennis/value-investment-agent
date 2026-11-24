"""Statement purpose uses formal acquisition, mapping, signing and canary owners."""

import base64
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fundamental_service.automatic_data_release import (
    AutomaticDataReleaseCandidateV1,
    AutomaticDataReleaseService,
    AutomaticStatementReleasePolicyV1,
    automatic_release_suite_digest,
)
from fundamental_service.data_releases import (
    DataReleaseError,
    DataReleaseVerifierV1,
    verify_data_release_candidate,
)
from fundamental_service.statement_release_builder import build_statement_release
from fundamental_service.statement_releases import (
    read_statement_release,
    statement_release_namespace,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_automatic_source_acquisition import acquire
from test_automatic_source_mapping import statement_source_case
from test_original_preparation import case, execute
from test_issuer_operating_release import inventory

KEY = Ed25519PrivateKey.from_private_bytes(
    b"synthetic-statement-release".ljust(32, b"0")
)


def release_case(tmp_path, monkeypatch):
    value = case(tmp_path / "source", monkeypatch, statement_original=True)
    prepared, _ = execute(value)
    request, *_ = statement_source_case(tmp_path / "request", monkeypatch)
    original_ref = value.service.reference(
        prepared.artifact_id, "sec-original-preparation-v1"
    )
    request = request.model_copy(update={"original_preparation": original_ref})
    ingestion = acquire(request, value.acquisition)
    assert ingestion.status == "degraded" and ingestion.canonical_fact_ids
    snapshots = SimpleNamespace(get=lambda key: value.metadata.snapshots[key])
    facts = SimpleNamespace(get=lambda key: value.metadata.facts[key])
    mappings = SimpleNamespace(get_mapping=lambda key: value.metadata.mappings[key])
    release = build_statement_release(
        original_ref,
        (ingestion,),
        originals=value.service,
        snapshots=snapshots,
        facts=facts,
        mappings=mappings,
        artifacts=value.artifacts,
        source_revision=request.source_revision,
        mapping_version=request.mapping_version,
    )
    statement = read_statement_release(release.manifest, artifacts=value.artifacts)
    policy = AutomaticStatementReleasePolicyV1(
        statement_profile=statement.projection.profile,
        mapping_version=request.mapping_version,
        parser_version=request.parser_version,
        validation_profile_digests=(ingestion.validation_profile_digest,),
        verifier_id="statement-machine",
        workflow_identity="synthetic/statement-release-v1",
    )
    roots = value.acquisition._automatic_authority().trust_roots.model_copy(
        update={
            "verifiers": {
                "statement-machine": DataReleaseVerifierV1(
                    workflow_identity=policy.workflow_identity,
                    public_key_ed25519_base64=base64.b64encode(
                        KEY.public_key().public_bytes_raw()
                    ).decode(),
                    verification_suite_digest=automatic_release_suite_digest(),
                )
            }
        }
    )
    options = dict(
        snapshots=snapshots,
        facts=facts,
        mappings=mappings,
        artifacts=value.artifacts,
        trust_roots=roots,
        policy=policy,
        private_key=KEY,
        source_revision=request.source_revision,
        statement_originals=value.service,
        statement_content=value.acquisition.content_store,
    )
    return value, release, statement, options


def test_partial_statement_release_signs_existing_gates_and_replays_without_market_or_valuation(
    tmp_path, monkeypatch
):
    value, request, statement, options = release_case(tmp_path, monkeypatch)
    receipt = AutomaticDataReleaseService(**options).verify_and_sign(request)
    assert receipt.decision.status == "passed", receipt.decision.issue_codes
    candidate = AutomaticDataReleaseCandidateV1.model_validate_json(
        value.artifacts.read(receipt.candidate_publication.artifact.artifact_id)
    )
    verify_data_release_candidate(
        candidate.manifest, candidate.verification, options["trust_roots"]
    )
    assert len(candidate.verification.passed_gate_ids) == 8
    assert receipt.decision.regulatory_evidence_digests
    assert not receipt.decision.market_policy_digests
    assert statement.statements.valuation_eligibility == "not_evaluated"
    assert candidate.manifest.profile_id == statement_release_namespace(
        statement.projection.scope,
        statement.projection.cutoff_at,
        statement.projection.profile.digest,
    )
    before = inventory(value.artifacts.root)
    repeated = AutomaticDataReleaseService(**options).verify_and_sign(request)
    assert not repeated.wrote and repeated.output_digest == receipt.output_digest
    assert inventory(value.artifacts.root) == before
    assert b"data_release_manifest_digest" not in canonical_bytes(statement)


def test_statement_manifest_requires_typed_retained_envelope_and_exact_namespace(
    tmp_path, monkeypatch
):
    value, request, _, options = release_case(tmp_path, monkeypatch)
    payload = request.manifest.model_dump(exclude={"manifest_digest"})
    payload["profile_id"] += "-changed"
    wrong = type(request.manifest).model_validate_json(
        canonical_bytes(payload | {"manifest_digest": sha256_digest(payload)})
    )
    with pytest.raises(DataReleaseError) as error:
        read_statement_release(wrong, artifacts=value.artifacts)
    assert error.value.code == "STATEMENT_RELEASE_CONTEXT_MISMATCH"
    refused = AutomaticDataReleaseService(**options).verify_and_sign(
        request.model_copy(update={"manifest": wrong})
    )
    assert (
        refused.decision.status == "blocked" and refused.candidate_publication is None
    )


def test_changed_canonical_fact_and_absent_original_owner_cannot_be_signed(
    tmp_path, monkeypatch
):
    value, request, statement, options = release_case(tmp_path, monkeypatch)
    absent = AutomaticDataReleaseService(
        **(options | {"statement_originals": None})
    ).verify_and_sign(request)
    assert (
        absent.decision.status == "blocked"
        and "STATEMENT_ORIGINAL_PREPARATION_UNAVAILABLE" in absent.decision.issue_codes
    )
    fact = statement.projection.facts[0].fact
    value.metadata.facts[fact.fact_id] = fact.model_copy(
        update={"value": fact.value + 1}
    )
    changed = AutomaticDataReleaseService(**options).verify_and_sign(request)
    assert (
        changed.decision.status == "blocked" and changed.candidate_publication is None
    )


def test_caller_cannot_relabel_mapping_abstention_as_not_applicable(
    tmp_path, monkeypatch
):
    from fundamental_service.contracts import MissingValueV1
    from fundamental_service.annual_statements import project_annual_statements
    from fundamental_service.statement_profiles import statement_executable_digest
    from fundamental_service.statement_releases import STATEMENT_RELEASE_ROLE

    value, request, statement, options = release_case(tmp_path, monkeypatch)
    first, *rest = statement.projection.missing_evidence
    changed = first.model_copy(
        update={
            "missing": MissingValueV1(
                status="not_applicable", reason="Caller declares not applicable"
            )
        }
    )
    projection = statement.projection.model_copy(
        update={"missing_evidence": (changed, *rest)}
    )
    envelope = statement.model_copy(
        update={
            "projection": projection,
            "statements": project_annual_statements(
                projection, executable_digest=statement_executable_digest()
            ),
        }
    )
    publication = value.artifacts.put_with_receipt(
        "synthetic-tampered-missing-" + sha256_digest(envelope), envelope
    )
    old_ref = next(
        ref
        for ref in request.manifest.artifact_refs
        if ref.role == STATEMENT_RELEASE_ROLE
    )
    new_ref = old_ref.model_copy(
        update={
            "artifact_id": publication.artifact.artifact_id,
            "content_hash": publication.artifact.content_hash,
        }
    )
    payload = request.manifest.model_dump(exclude={"manifest_digest"}) | {
        "artifact_refs": tuple(
            new_ref if ref == old_ref else ref for ref in request.manifest.artifact_refs
        )
    }
    manifest = type(request.manifest).model_validate_json(
        canonical_bytes(payload | {"manifest_digest": sha256_digest(payload)})
    )
    content = request.content.model_copy(
        update={
            "evidence_refs": tuple(
                new_ref if ref == old_ref else ref
                for ref in request.content.evidence_refs
            )
        }
    )
    receipt = AutomaticDataReleaseService(**options).verify_and_sign(
        request.model_copy(update={"manifest": manifest, "content": content})
    )
    assert receipt.decision.status == "blocked"
    assert "STATEMENT_MISSING_EVIDENCE_MISMATCH" in receipt.decision.issue_codes
    assert receipt.candidate_publication is None


def test_authenticated_statement_read_preserves_release_cutoff_values_and_rejects_mismatch(
    tmp_path, monkeypatch
):
    from datetime import timedelta
    from fastapi.testclient import TestClient
    from fundamental_service.app import create_app
    from fundamental_service.operations import OperationsConfig
    from fundamental_service.testsupport import (
        TEST_SERVICE_TOKEN,
        auth_headers,
        make_internal_envelope,
    )

    value, request, statement, options = release_case(tmp_path, monkeypatch)
    receipt = AutomaticDataReleaseService(**options).verify_and_sign(request)
    candidate = AutomaticDataReleaseCandidateV1.model_validate_json(
        value.artifacts.read(receipt.candidate_publication.artifact.artifact_id)
    )
    metadata = SimpleNamespace(
        get_data_release_manifest=lambda digest: candidate.manifest
        if digest == candidate.manifest.manifest_digest
        else None,
        get_data_release_verification=lambda digest: candidate.verification,
        get_mapping=options["mappings"].get_mapping,
    )
    app = create_app(
        snapshot_repository=options["snapshots"],
        artifact_store=value.artifacts,
        content_store=value.acquisition.content_store,
        fact_repository=options["facts"],
        metadata_store=metadata,
        statement_originals=value.service,
        config=OperationsConfig(service_token=TEST_SERVICE_TOKEN),
    )
    client = TestClient(app)
    payload = {
        "contract_version": "fundamental.annual-statements.v1",
        "data_release_manifest_digest": candidate.manifest.manifest_digest,
        "cutoff_at": statement.projection.cutoff_at.isoformat(),
    }
    response = client.post(
        "/v1/data/annual-statements",
        headers=auth_headers(),
        json=make_internal_envelope(payload),
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["data_release_manifest_digest"] == candidate.manifest.manifest_digest
    assert result["statements"] == statement.statements.model_dump(mode="json")
    wrong = payload | {
        "cutoff_at": (statement.projection.cutoff_at + timedelta(days=1)).isoformat()
    }
    refused = client.post(
        "/v1/data/annual-statements",
        headers=auth_headers(),
        json=make_internal_envelope(wrong),
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "STATEMENT_CUTOFF_MISMATCH"
    assert (
        client.post(
            "/v1/data/annual-statements", json=make_internal_envelope(payload)
        ).status_code
        == 401
    )
    schema = app.openapi()
    operation = schema["paths"]["/v1/data/annual-statements"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("FundamentalAnnualStatementsRequestEnvelopeV1")


def test_statement_candidate_survives_postgres_restart_without_overwriting_inputs(
    tmp_path, monkeypatch, recovery_databases
):
    from fundamental_service.metadata import (
        PostgresMetadataStore,
        PostgresContentStore,
        PostgresArtifactStore,
    )

    value, request, statement, options = release_case(tmp_path, monkeypatch)
    receipt = AutomaticDataReleaseService(**options).verify_and_sign(request)
    candidate = AutomaticDataReleaseCandidateV1.model_validate_json(
        value.artifacts.read(receipt.candidate_publication.artifact.artifact_id)
    )
    database, _ = recovery_databases
    content_root = tmp_path / "postgres-content"
    metadata = PostgresMetadataStore(
        database, auto_migrate=True, data_release_trust_roots=options["trust_roots"]
    )
    metadata.start()
    try:
        artifacts = PostgresArtifactStore(
            metadata, PostgresContentStore(content_root, metadata)
        )
        for reference in request.manifest.artifact_refs:
            record = value.artifacts.get(reference.artifact_id)
            artifacts.put_bytes_with_receipt(
                record.artifact_id,
                value.artifacts.read(record.artifact_id),
                dependency_hashes=record.dependency_hashes,
                media_type=record.media_type,
            )
        metadata.publish_data_release_candidate(
            candidate.manifest, candidate.verification
        )
    finally:
        metadata.close()
    before = inventory(content_root)
    metadata = PostgresMetadataStore(
        database, data_release_trust_roots=options["trust_roots"]
    )
    metadata.start()
    try:
        artifacts = PostgresArtifactStore(
            metadata, PostgresContentStore(content_root, metadata)
        )
        manifest = metadata.get_data_release_manifest(
            candidate.manifest.manifest_digest
        )
        assert manifest == candidate.manifest
        assert (
            metadata.get_data_release_verification(candidate.manifest.manifest_digest)
            == candidate.verification
        )
        assert read_statement_release(manifest, artifacts=artifacts) == statement
        metadata.publish_data_release_candidate(
            candidate.manifest, candidate.verification
        )
        assert inventory(content_root) == before
    finally:
        metadata.close()
