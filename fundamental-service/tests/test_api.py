from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from fundamental_service.app import create_app
from fundamental_service.contracts import QualityStatus, UncertaintyV1
from fundamental_service.operations import OperationsConfig
from fundamental_service.replay import ArtifactStore
from fundamental_service.snapshots import FilesystemContentStore
from fundamental_service.testsupport import (
    TEST_SERVICE_TOKEN,
    auth_headers,
    make_internal_envelope,
    make_valuation,
)


class _SnapshotRepository:
    def __init__(self):
        valuation = make_valuation()
        self.snapshot = SimpleNamespace(
            snapshot_id="snapshot-1",
            identity=valuation.identity,
            valuation_timestamp=valuation.valuation_context.valuation_timestamp,
            source_records=(SimpleNamespace(content_hash="test-source"),),
        )

    def get(self, snapshot_id: str):
        self.snapshot.snapshot_id = snapshot_id
        return self.snapshot


class _ResolvingSnapshotRepository(_SnapshotRepository):
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def find(self, *, identity, valuation_timestamp):
        if (
            identity.issuer_id == self.snapshot.identity.issuer_id
            and valuation_timestamp >= self.snapshot.valuation_timestamp
        ):
            return (self.snapshot,)
        return ()


class _FactRepository:
    def get(self, fact_id: str):
        return SimpleNamespace(
            fact_id=fact_id,
            issuer_id="CIK1",
            security_id="COMMON",
            quality=QualityStatus.VERIFIED,
            available_at=datetime(2025, 1, 1, tzinfo=UTC),
            source=SimpleNamespace(content_hash="test-source"),
        )

    def resolve(self, *, snapshot, valuation_timestamp, required_fields):
        _ = snapshot, valuation_timestamp
        return tuple(
            SimpleNamespace(fact_id=f"fact-{field}") for field in required_fields
        )


class _ForeignFactRepository(_FactRepository):
    def get(self, fact_id: str):
        fact = super().get(fact_id)
        fact.issuer_id = "CIK-FOREIGN"
        return fact


def test_readiness_distinguishes_missing_snapshot_dependency():
    client = TestClient(create_app())
    assert client.get("/readyz").json() == {
        "contract_version": "internal.v1",
        "status": "not_ready",
    }


def test_snapshot_resolution_returns_service_owned_snapshot_and_fact_refs():
    valuation = make_valuation()
    snapshot = SimpleNamespace(
        snapshot_id="snapshot-resolved",
        identity=valuation.identity,
        valuation_timestamp=valuation.valuation_context.valuation_timestamp,
        coverage_status=QualityStatus.VERIFIED,
        issues=(),
        parser_version="parser-v1",
        taxonomy_manifest_id="taxonomy-v1",
        policy_version="policy-v1",
        source_records=(),
    )
    client = TestClient(
        create_app(
            _ResolvingSnapshotRepository(snapshot),
            fact_repository=_FactRepository(),
        )
    )
    selector = {
        "contract_version": "fundamental.v1",
        "identity": valuation.identity.model_dump(mode="json"),
        "valuation_timestamp": (
            valuation.valuation_context.valuation_timestamp.isoformat()
        ),
        "source_selection_policy": "pit-v1",
        "coverage_profile": "us-gaap-public-v1",
        "required_fields": ["revenue"],
    }
    response = client.post(
        "/v1/data/snapshots/resolve",
        headers=auth_headers(),
        json=make_internal_envelope(selector),
    )
    assert response.status_code == 200
    assert response.json()["result"]["snapshot_id"] == "snapshot-resolved"
    assert response.json()["result"]["historical_facts"] == ["fact-revenue"]


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
    response = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    ).post(
        "/v1/valuation/uncertainty",
        headers=auth_headers(),
        json=make_internal_envelope(payload),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "internal.v1"
    assert body["schema_version"] == "fundamental.v1"
    assert body["result"]["valid_samples"] == 10
    assert body["result"]["scenario_results"]


def test_calculate_accepts_explicit_monte_carlo_controls_for_base_result():
    valuation = (
        make_valuation()
        .model_copy(
            update={
                "uncertainty": UncertaintyV1(
                    mode="monte_carlo",
                    samples=5,
                    seed=7,
                    invalid_draw_policy="skip",
                    parameters=(
                        {
                            "path": "assumptions.terminal_growth",
                            "distribution": "uniform",
                            "lower": Decimal("0.01"),
                            "upper": Decimal("0.03"),
                        },
                    ),
                ),
            }
        )
        .with_digest()
    )
    payload = valuation.model_dump(mode="json")
    payload["caller_approval"] = {
        "input_digest": valuation.input_digest,
        "decision": "approved",
        "caller_id": "test-agent",
        "decided_at": datetime.now(UTC).isoformat(),
    }
    response = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    ).post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=make_internal_envelope(payload),
    )
    assert response.status_code == 200
    assert response.json()["result"]["input_digest"] == valuation.input_digest


def test_uncertainty_accepts_the_validated_request_and_same_caller_approval():
    valuation = (
        make_valuation()
        .model_copy(
            update={
                "uncertainty": UncertaintyV1(
                    mode="monte_carlo",
                    samples=5,
                    seed=7,
                    invalid_draw_policy="skip",
                    parameters=(
                        {
                            "path": "assumptions.terminal_growth",
                            "distribution": "uniform",
                            "lower": Decimal("0.01"),
                            "upper": Decimal("0.03"),
                        },
                    ),
                ),
            }
        )
        .with_digest()
    )
    payload = valuation.model_dump(mode="json")
    payload["caller_approval"] = {
        "input_digest": valuation.input_digest,
        "decision": "approved",
        "caller_id": "test-agent",
        "decided_at": datetime.now(UTC).isoformat(),
    }
    payload["monte_carlo"] = {
        "uncertainty": payload["uncertainty"],
        "sampler_version": "python-random-v1",
    }
    response = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    ).post(
        "/v1/valuation/uncertainty",
        headers=auth_headers(),
        json=make_internal_envelope(payload),
    )
    assert response.status_code == 200
    assert response.json()["result"]["base"]["snapshot_id"] == "snapshot-1"


def test_liveness_is_public_and_readiness_requires_all_runtime_dependencies(
    tmp_path: Path,
):
    client = TestClient(
        create_app(
            _SnapshotRepository(),
            ArtifactStore(tmp_path / "artifacts"),
            FilesystemContentStore(tmp_path / "content"),
            fact_repository=_FactRepository(),
            config=OperationsConfig(service_token=TEST_SERVICE_TOKEN),
        )
    )
    assert client.get("/livez").status_code == 200
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json() == {"contract_version": "internal.v1", "status": "ready"}


def test_internal_endpoints_require_signed_context_and_redact_credentials():
    client = TestClient(
        create_app(config=OperationsConfig(service_token="super-secret-token"))
    )
    response = client.request(
        "GET",
        "/v1/data/snapshots/snapshot-1",
        json={"context": {}, "input": {}},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "internal_auth_missing"
    assert "super-secret-token" not in response.text
    assert body["correlation_id"] == response.headers["X-Correlation-ID"]


def test_expired_deadline_and_calculation_budget_are_stable_errors():
    value = make_valuation().model_dump(mode="json")
    client = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    )
    expired = client.post(
        "/v1/valuation/uncertainty",
        headers=auth_headers(),
        json=make_internal_envelope(
            {**value, "scenarios": [], "sensitivity": [], "monte_carlo": None},
            deadline_at=datetime(2020, 1, 1, tzinfo=UTC),
            issued_at=datetime(2019, 1, 1, tzinfo=UTC),
        ),
    )
    assert expired.status_code == 408
    assert expired.json()["error"]["code"] == "REQUEST_DEADLINE_EXCEEDED"

    limited = TestClient(
        create_app(
            _SnapshotRepository(),
            fact_repository=_FactRepository(),
            config=OperationsConfig(
                service_token=TEST_SERVICE_TOKEN, max_calculation_samples=2
            ),
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
    budget = limited.post(
        "/v1/valuation/uncertainty",
        headers=auth_headers(),
        json=make_internal_envelope(value),
    )
    assert budget.status_code == 422
    assert budget.json()["error"]["code"] == "CALCULATION_BUDGET_EXCEEDED"


def test_calculation_dependency_outage_is_unavailable_without_local_fallback():
    client = TestClient(create_app())
    response = client.post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=make_internal_envelope(make_valuation().model_dump(mode="json")),
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "source_unavailable"


def test_validation_rejects_fact_outside_selected_snapshot():
    client = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_ForeignFactRepository())
    )
    response = client.post(
        "/v1/valuation/validate",
        headers=auth_headers(),
        json=make_internal_envelope(make_valuation().model_dump(mode="json")),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACT_PROVENANCE_MISMATCH"


def test_valid_bearer_without_signed_context_is_rejected():
    client = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    )
    response = client.post(
        "/v1/valuation/calculate",
        headers={"Authorization": f"Bearer {TEST_SERVICE_TOKEN}"},
        json={"input": make_valuation().model_dump(mode="json")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_signed_context_claims_are_bound_to_audience_and_organization():
    client = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    )
    payload = make_valuation().model_dump(mode="json")
    wrong_audience = make_internal_envelope(payload, audience="search-service")
    response = client.post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=wrong_audience,
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "internal_context_claims_invalid"

    mismatched_org = make_internal_envelope(payload)
    response = client.post(
        "/v1/valuation/calculate",
        headers=auth_headers(organization_id="organization-attacker"),
        json=mismatched_org,
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "internal_context_organization_mismatch"


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
