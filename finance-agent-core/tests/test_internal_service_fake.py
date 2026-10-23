from fastapi.testclient import TestClient

from src.shared.internal_services import INTERNAL_CONTRACT_VERSION
from tests.fakes.internal_capability_service import create_fake_internal_service


def _body() -> dict[str, object]:
    return {
        "context": {
            "principal": {"subject_id": "user-123"},
            "correlation_id": "correlation-123",
            "contract_version": INTERNAL_CONTRACT_VERSION,
            "deadline_at": "2026-10-23T18:30:00Z",
        },
        "input": {"query": "example"},
    }


def test_fake_service_authenticates_and_echoes_shared_response_metadata() -> None:
    client = TestClient(create_fake_internal_service(expected_token="service-secret"))

    response = client.post(
        "/v1/fake",
        headers={"Authorization": "Bearer service-secret"},
        json=_body(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "correlation_id": "correlation-123",
        "contract_version": INTERNAL_CONTRACT_VERSION,
        "result": {"echo": {"query": "example"}},
    }


def test_fake_service_rejects_bad_auth_before_accepting_principal() -> None:
    client = TestClient(create_fake_internal_service(expected_token="service-secret"))
    body = _body()
    body["context"] = {
        **body["context"],
        "principal": {"user_id": "attacker-selected"},
    }

    response = client.post(
        "/v1/fake",
        headers={"Authorization": "Bearer wrong"},
        json=body,
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "internal_auth_invalid"


def test_fake_service_readiness_is_versioned_and_redacted() -> None:
    client = TestClient(create_fake_internal_service(expected_token="service-secret"))

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "contract_version": INTERNAL_CONTRACT_VERSION,
    }
    assert "service-secret" not in response.text
