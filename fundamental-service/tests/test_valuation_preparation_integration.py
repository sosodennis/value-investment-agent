from pathlib import Path

from fastapi.testclient import TestClient
from fundamental_service.app import create_app
from fundamental_service.testsupport import (
    auth_headers,
    make_internal_envelope,
)
from test_preparation_runner import _fixture


def test_http_prepare_composes_complete_release_and_policy_inputs(tmp_path: Path):
    fixture = _fixture(tmp_path)
    manifest = fixture.manifest
    snapshot = fixture.snapshot
    app = create_app(
        snapshot_repository=fixture.snapshots,
        fact_repository=fixture.facts,
        artifact_store=fixture.artifacts,
        metadata_store=fixture.metadata,
        config=fixture.application.config,
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
