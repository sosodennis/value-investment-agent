from pathlib import Path

from fastapi.testclient import TestClient
from fundamental_service.app import create_app
from fundamental_service.operations import OperationsConfig
from fundamental_service.replay import ArtifactStore
from fundamental_service.snapshots import FilesystemContentStore
from fundamental_service.testsupport import make_valuation


class _SnapshotRepository:
    def get(self, snapshot_id: str):
        return {"snapshot_id": snapshot_id}


def test_readiness_distinguishes_missing_snapshot_dependency():
    client = TestClient(create_app())
    assert client.get("/readyz").json() == {
        "contract_version": "internal.v1",
        "status": "not_ready",
    }


def test_uncertainty_endpoint_runs_the_shared_calculator():
    payload = make_valuation().model_dump(mode="json")
    payload["scenarios"] = [
        {"name": "base", "assumptions": {}},
        {"name": "downside", "assumptions": {"assumptions.terminal_growth": "0.01"}},
        {"name": "upside", "assumptions": {"assumptions.terminal_growth": "0.03"}},
    ]
    payload["sensitivity"] = [
        {"path": "assumptions.terminal_growth", "values": ["0.01", "0.03"]}
    ]
    payload["monte_carlo"] = {
        "uncertainty": {
            "mode": "monte_carlo",
            "samples": 10,
            "seed": 7,
            "invalid_draw_policy": "skip",
            "parameters": [
                {
                    "path": "assumptions.terminal_growth",
                    "distribution": "uniform",
                    "lower": "0.01",
                    "upper": "0.03",
                }
            ],
        }
    }
    response = TestClient(create_app(_SnapshotRepository())).post(
        "/v1/valuation/uncertainty", json=payload
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid_samples"] == 10
    assert body["scenario_results"]


def test_liveness_is_public_and_readiness_requires_all_runtime_dependencies(
    tmp_path: Path,
):
    client = TestClient(
        create_app(
            _SnapshotRepository(),
            ArtifactStore(tmp_path / "artifacts"),
            FilesystemContentStore(tmp_path / "content"),
            config=OperationsConfig(
                auth_token="integration-token",
                signing_key="integration-signing-key",
            ),
        )
    )
    assert client.get("/livez").status_code == 200
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json() == {"contract_version": "internal.v1", "status": "ok"}


def test_internal_endpoints_require_bearer_auth_and_redact_credentials():
    client = TestClient(
        create_app(
            config=OperationsConfig(
                auth_token="super-secret-token",
                signing_key="signing-key",
            )
        )
    )
    response = client.get("/v1/data/snapshots/snapshot-1")
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "AUTHENTICATION_FAILED"
    assert "super-secret-token" not in response.text
    assert body["correlation_id"] == response.headers["X-Correlation-ID"]


def test_expired_deadline_and_calculation_budget_are_stable_errors():
    value = make_valuation().model_dump(mode="json")
    client = TestClient(create_app(_SnapshotRepository()))
    expired = client.post(
        "/v1/valuation/uncertainty",
        headers={"X-Request-Deadline": "2020-01-01T00:00:00Z"},
        json={**value, "scenarios": [], "sensitivity": [], "monte_carlo": None},
    )
    assert expired.status_code == 408
    assert expired.json()["code"] == "REQUEST_DEADLINE_EXCEEDED"

    limited = TestClient(
        create_app(
            _SnapshotRepository(),
            config=OperationsConfig(max_calculation_samples=2, require_auth=False),
        )
    )
    value["monte_carlo"] = {
        "uncertainty": {
            "mode": "monte_carlo",
            "samples": 3,
            "seed": 7,
            "invalid_draw_policy": "skip",
            "parameters": [
                {
                    "path": "assumptions.terminal_growth",
                    "distribution": "uniform",
                    "lower": "0.01",
                    "upper": "0.03",
                }
            ],
        }
    }
    budget = limited.post("/v1/valuation/uncertainty", json=value)
    assert budget.status_code == 422
    assert budget.json()["code"] == "CALCULATION_BUDGET_EXCEEDED"


def test_calculation_dependency_outage_is_unavailable_without_local_fallback():
    client = TestClient(create_app())
    response = client.post(
        "/v1/valuation/calculate", json=make_valuation().model_dump(mode="json")
    )
    assert response.status_code == 503
    assert response.json()["code"] == "SOURCE_UNAVAILABLE"


def test_artifact_survives_store_restart_and_cache_reset(tmp_path: Path):
    first = ArtifactStore(tmp_path / "artifacts")
    record = first.put("release-1", {"result": "immutable"})
    first.reset_operational_cache()
    second = ArtifactStore(tmp_path / "artifacts")
    assert second.get(record.artifact_id) == record
    assert second.read(record.artifact_id) == b'{"result":"immutable"}'


def test_metrics_declare_operational_quality_and_dependency_signals():
    body = TestClient(create_app()).get("/metrics").text
    for metric in (
        "source_health_failures_total",
        "snapshot_freshness_failures_total",
        "cache_hit_total",
        "cache_miss_total",
        "cache_stale_total",
        "calculation_latency_ms_total",
        "calculation_budget_failures_total",
        "quality_status_total",
        "abstention_total",
        "provenance_replay_failures_total",
        "provider_degradation_total",
    ):
        assert f"fundamental_service_{metric}" in body
