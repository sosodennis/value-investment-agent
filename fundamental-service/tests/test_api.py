from fastapi.testclient import TestClient

from fundamental_service.app import create_app
from fundamental_service.testsupport import make_valuation


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
    response = TestClient(create_app(object())).post(
        "/v1/valuation/uncertainty", json=payload
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid_samples"] == 10
    assert body["scenario_results"]
