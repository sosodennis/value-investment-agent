from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from fundamental_service.app import create_app
from fundamental_service.data_releases import DataReleaseManifestV1
from fundamental_service.operations import OperationsConfig
from fundamental_service.serialization import sha256_digest
from fundamental_service.snapshots import FilesystemContentStore
from fundamental_service.testsupport import (
    TEST_SERVICE_TOKEN,
    auth_headers,
    make_internal_envelope,
)
from fundamental_service.valuation_requirements import valuation_requirements_profile
from test_api import _release_manifest_for
from test_postgres_metadata import _snapshot
from test_valuation_preparation import _facts


class _CompleteFactRepository:
    def __init__(self, facts):
        self._facts = {fact.fact_id: fact for fact in facts}

    def get(self, fact_id: str):
        return self._facts[fact_id]


def _complete_manifest(snapshot, facts) -> DataReleaseManifestV1:
    base = _release_manifest_for(snapshot, facts)
    payload = base.model_dump(mode="python")
    payload["required_fields"] = valuation_requirements_profile(
        "fcff_dcf"
    ).required_fact_fields
    payload["manifest_digest"] = sha256_digest(
        {key: value for key, value in payload.items() if key != "manifest_digest"}
    )
    return DataReleaseManifestV1(**payload)


def test_http_prepare_composes_complete_release_and_policy_inputs(tmp_path: Path):
    facts = tuple(
        fact.model_copy(
            update={
                "captured_at": fact.available_at,
                "source": fact.source.model_copy(
                    update={
                        "available_at": fact.available_at,
                        "captured_at": fact.available_at,
                    }
                ),
            }
        )
        for fact in _facts()
    )
    snapshot = _snapshot(
        "complete-preparation",
        identity={
            "issuer_id": "CIK1",
            "issuer_name": "Example Co",
            "domicile": "US",
            "reporting_basis": "us-gaap",
            "security_id": "COMMON",
            "share_class": "common",
            "currency": "USD",
        },
        valuation_timestamp=datetime(2026, 3, 1, tzinfo=UTC),
    )
    manifest = _complete_manifest(snapshot, facts)

    class _Metadata:
        def get_data_release_manifest(self, digest: str):
            return manifest if digest == manifest.manifest_digest else None

    app = create_app(
        snapshot_repository=type(
            "SnapshotRepository",
            (),
            {"get": lambda _self, _snapshot_id: snapshot},
        )(),
        fact_repository=_CompleteFactRepository(facts),
        artifact_store=None,
        content_store=FilesystemContentStore(tmp_path / "content"),
        metadata_store=_Metadata(),
        config=OperationsConfig(service_token=TEST_SERVICE_TOKEN),
    )

    client = TestClient(app)
    request_payload = make_internal_envelope(
        {
            "contract_version": "fundamental.v1",
            "snapshot_id": snapshot.snapshot_id,
            "data_release_manifest_digest": manifest.manifest_digest,
            "model_id": "fcff_dcf",
        }
    )
    response = client.post(
        "/v1/valuation/prepare",
        headers=auth_headers(),
        json=request_payload,
    )

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["status"] == "prepared"
    assert result["quality_status"] == "provisional"
    assert result["input"]["assumptions"]["wacc"]["risk_free_rate"] == "0.046"
    assert result["input"]["valuation_context"]["data_release_manifest_digest"] == (
        manifest.manifest_digest
    )
    assert any(
        item["path"] == "assumptions.wacc.risk_free_rate"
        and item["source_refs"]
        and item["as_of"] == "2025-01-03T00:00:00Z"
        and item["method"] == "approved_source"
        for item in result["assumptions_evidence"]
    )
    assert (
        next(
            item
            for item in result["assumptions_evidence"]
            if item["path"] == "assumptions.wacc.debt_weight"
        )["method"]
        == "approved_policy"
    )
    assert len(result["preparation_digest"]) == 64

    repeat = client.post(
        "/v1/valuation/prepare",
        headers=auth_headers(),
        json=request_payload,
    )
    assert repeat.status_code == 200, repeat.text
    repeat_result = repeat.json()["result"]
    assert repeat_result["status"] == "prepared"
    assert repeat_result["quality_status"] == "provisional"
    assert repeat_result["preparation_digest"] == result["preparation_digest"]
