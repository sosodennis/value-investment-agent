from __future__ import annotations

import httpx
import pytest

from api.server import app
from src.auth.interface.contracts import Principal
from src.llm_provider.application.wiring import get_provider_settings_service
from src.llm_provider.composition.routes import _read_principal, _write_principal
from src.llm_provider.domain.errors import ProviderSettingsError
from src.llm_provider.domain.provider_models import ManagedProviderKey, OpenRouterModel
from src.llm_provider.interface.contracts import ProviderKeyImportBatchResponse


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


class _Service:
    def __init__(self) -> None:
        self.key = ManagedProviderKey(
            "managed-a", "primary", "9abc", "fingerprint-a", None
        )
        self.models = (
            OpenRouterModel("openrouter/free", "Free Models Router", "router", None),
        )
        self.calls: list[tuple[str, object]] = []
        self.test_result = True
        self.replacement_error_code = "replacement_must_differ"
        self.import_error_code: str | None = None
        self.import_batch = ProviderKeyImportBatchResponse(
            id="00000000-0000-0000-0000-000000000192",
            status="queued",
            total_count=1,
            processed_count=0,
            imported_count=0,
            duplicate_count=0,
            invalid_count=0,
            retryable_count=0,
            created_at="2026-10-31T00:00:00Z",
            updated_at="2026-10-31T00:00:00Z",
        )

    async def list_keys(
        self, *, user_id: str, organization_id: str, membership_id: str
    ):
        self.calls.append(("list_keys", (user_id, organization_id, membership_id)))
        return [self.key]

    async def replace_key(
        self,
        *,
        user_id: str,
        key_id: str,
        key: str,
        label: str,
        organization_id: str,
        membership_id: str,
    ):
        self.calls.append(
            (
                "replace_key",
                (user_id, key_id, key, label, organization_id, membership_id),
            )
        )
        raise ProviderSettingsError(self.replacement_error_code)

    async def test_key(
        self, *, user_id: str, key_id: str, organization_id: str, membership_id: str
    ):
        self.calls.append(
            ("test_key", (user_id, key_id, organization_id, membership_id))
        )
        return self.test_result

    async def delete_key(
        self, *, user_id: str, key_id: str, organization_id: str, membership_id: str
    ):
        self.calls.append(
            ("delete_key", (user_id, key_id, organization_id, membership_id))
        )

    async def create_key_import(
        self,
        *,
        user_id: str,
        organization_id: str,
        membership_id: str,
        idempotency_key: str,
        items: list[dict[str, object]],
    ):
        self.calls.append(
            (
                "create_key_import",
                (user_id, organization_id, membership_id, idempotency_key, items),
            )
        )
        if self.import_error_code is not None:
            raise ProviderSettingsError(self.import_error_code)
        return self.import_batch

    async def selected_model_settings(
        self, *, user_id: str, organization_id: str, membership_id: str
    ):
        _ = user_id
        self.calls.append(
            ("selected_model_settings", (user_id, organization_id, membership_id))
        )
        return "openrouter/free", self.models

    async def update_selected_model(
        self,
        *,
        model_id: str,
        user_id: str,
        organization_id: str,
        membership_id: str,
    ):
        self.calls.append(
            (
                "update_selected_model",
                (model_id, user_id, organization_id, membership_id),
            )
        )
        if model_id != "openrouter/free":
            raise ProviderSettingsError("model_not_free")
        return model_id


def _client(service: _Service) -> httpx.AsyncClient:
    principal = Principal(
        user_id="user-a",
        subject="user-a",
        email="user-a@example.test",
        organization_id="organization-a",
        membership_id="membership-a",
    )
    app.dependency_overrides[_read_principal] = lambda: principal
    app.dependency_overrides[_write_principal] = lambda: principal
    app.dependency_overrides[get_provider_settings_service] = lambda: service
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


@pytest.mark.asyncio
async def test_provider_settings_require_authenticated_user_even_with_admin_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER_ADMIN_TOKEN", "legacy-admin-token")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/v1/llm/provider-keys",
            headers={"Authorization": "Bearer legacy-admin-token"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_provider_key_routes_delegate_to_provider_service() -> None:
    service = _Service()
    async with _client(service) as client:
        listed = await client.get("/api/v1/llm/provider-keys")
        created = await client.post(
            "/api/v1/llm/provider-keys",
            json={"api_key": "sk-this-is-a-long-test-secret", "label": "primary"},
            headers={"Idempotency-Key": "manual-request-192-key"},
        )
        tested = await client.post("/api/v1/llm/provider-keys/managed-a/test")
        deleted = await client.delete("/api/v1/llm/provider-keys/managed-a")
    assert listed.status_code == 200
    assert created.status_code == 202
    assert "sk-this-is-a-long-test-secret" not in created.text
    assert tested.status_code == 200
    assert deleted.status_code == 204
    assert [call[0] for call in service.calls] == [
        "list_keys",
        "create_key_import",
        "test_key",
        "delete_key",
    ]
    assert service.calls[1][1] == (
        "user-a",
        "organization-a",
        "membership-a",
        "manual-request-192-key",
        [
            {
                "source_line": 1,
                "label": "primary",
                "api_key": "sk-this-is-a-long-test-secret",
            }
        ],
    )


@pytest.mark.asyncio
async def test_invalid_provider_key_validation_does_not_echo_secret_input() -> None:
    service = _Service()
    canary = "sk-short-canary-123"
    async with _client(service) as client:
        response = await client.post(
            "/api/v1/llm/provider-keys",
            json={"api_key": canary, "label": "test"},
        )

    assert response.status_code == 422
    assert canary not in response.text


@pytest.mark.asyncio
async def test_manual_import_idempotency_conflict_is_returned_as_conflict() -> None:
    service = _Service()
    service.import_error_code = "idempotency_key_reused"
    async with _client(service) as client:
        response = await client.post(
            "/api/v1/llm/provider-keys",
            json={"api_key": "sk-this-is-a-long-test-secret", "label": "primary"},
            headers={"Idempotency-Key": "manual-request-192-key"},
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "idempotency_key_reused"}
    assert "sk-this-is-a-long-test-secret" not in response.text


@pytest.mark.asyncio
async def test_file_import_preview_and_submit_do_not_return_key_material() -> None:
    service = _Service()
    canary = "sk-or-v1-synthetic-credential-0001"
    file = ("keys.txt", f"{canary}\n{canary}\n".encode(), "text/plain")
    async with _client(service) as client:
        preview = await client.post(
            "/api/v1/llm/provider-keys/imports/preview",
            files={"file": file},
        )
        submitted = await client.post(
            "/api/v1/llm/provider-keys/imports",
            files={"file": file},
            headers={"Idempotency-Key": "import-request-192-key"},
        )

    assert preview.status_code == 200
    assert preview.json() == {
        "file_type": "txt",
        "row_count": 2,
        "unique_count": 1,
        "duplicate_count": 1,
        "issues": [],
    }
    assert submitted.status_code == 202
    assert canary not in preview.text
    assert canary not in submitted.text
    assert service.calls[-1][0] == "create_key_import"
    _, request = service.calls[-1]
    assert request[3] == "import-request-192-key"
    assert len(request[4]) == 2


@pytest.mark.asyncio
async def test_file_import_rejects_malformed_rows_without_echoing_values() -> None:
    service = _Service()
    canary = "sk-or-v1-synthetic-credential-0001"
    async with _client(service) as client:
        response = await client.post(
            "/api/v1/llm/provider-keys/imports",
            files={"file": ("keys.csv", f"api_key\n{canary}\nshort\n".encode())},
            headers={"Idempotency-Key": "import-request-192-invalid"},
        )

    assert response.status_code == 422
    assert response.json()["detail"]["issues"] == [
        {"source_line": 3, "code": "invalid_csv_row"}
    ]
    assert canary not in response.text
    assert service.calls == []


@pytest.mark.asyncio
async def test_provider_key_route_preserves_failed_test_result() -> None:
    service = _Service()
    service.test_result = False
    async with _client(service) as client:
        response = await client.post("/api/v1/llm/provider-keys/managed-a/test")
    assert response.status_code == 200
    assert response.json() == {
        "id": "managed-a",
        "passed": False,
        "status": "unavailable",
    }


@pytest.mark.asyncio
async def test_replacement_error_is_actionable_at_the_public_api() -> None:
    service = _Service()
    async with _client(service) as client:
        response = await client.post(
            "/api/v1/llm/provider-keys/managed-a/replace",
            json={"api_key": "same-key-material-over-twenty", "label": "primary"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "replacement key must differ from the current key"
    )


@pytest.mark.asyncio
async def test_replacement_in_progress_is_a_conflict_at_the_public_api() -> None:
    service = _Service()
    service.replacement_error_code = "replacement_in_progress"
    async with _client(service) as client:
        response = await client.post(
            "/api/v1/llm/provider-keys/managed-a/replace",
            json={"api_key": "new-key-material-over-twenty", "label": "primary"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "a key replacement is already in progress"


@pytest.mark.asyncio
async def test_settings_routes_delegate_and_map_validation_errors() -> None:
    service = _Service()
    async with _client(service) as client:
        read = await client.get("/api/v1/llm/settings")
        updated = await client.put(
            "/api/v1/llm/settings", json={"selected_model": "openrouter/free"}
        )
        rejected = await client.put(
            "/api/v1/llm/settings", json={"selected_model": "paid/model"}
        )
    assert read.status_code == 200
    assert updated.status_code == 200
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "model_not_free"
