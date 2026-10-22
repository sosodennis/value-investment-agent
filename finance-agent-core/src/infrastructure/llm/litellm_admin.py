"""Small, redacting client for the internal LiteLLM model-management API."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Final
from uuid import uuid4

import httpx

from src.shared.llm.routes import DEFAULT_MODEL_ALIAS

MANAGED_MARKER: Final = "value_investment_agent_managed"
OPENROUTER_BASE_URL: Final = "https://openrouter.ai/api/v1"


class LiteLLMAdminError(RuntimeError):
    """A sanitized error raised for a failed management operation."""


@dataclass(frozen=True)
class ManagedKey:
    id: str
    label: str
    suffix: str
    fingerprint: str
    created_at: str | None


def key_suffix(value: str) -> str:
    return value[-4:] if len(value) >= 4 else "****"


def key_fingerprint(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:12]


class LiteLLMAdminClient:
    """Manage only deployments created by this project UI."""

    def __init__(
        self,
        *,
        base_url: str,
        admin_token: str,
        openrouter_headers: Mapping[str, str],
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        gateway_url = base_url.rstrip("/")
        self._base_url = (
            gateway_url.removesuffix("/v1")
            if gateway_url.endswith("/v1")
            else gateway_url
        )
        self._admin_token = admin_token
        self._openrouter_headers = dict(openrouter_headers)
        self._http_client = http_client

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def list_managed(self) -> list[ManagedKey]:
        payload = await self._request("GET", "/model/info")
        models = payload.get("data", payload) if isinstance(payload, Mapping) else []
        if not isinstance(models, list):
            return []

        result: list[ManagedKey] = []
        for model in models:
            if not isinstance(model, Mapping):
                continue
            info = model.get("model_info")
            if not isinstance(info, Mapping) or info.get(MANAGED_MARKER) is not True:
                continue
            model_id = info.get("id") or model.get("model_id") or model.get("id")
            if not isinstance(model_id, str) or not model_id:
                continue
            result.append(
                ManagedKey(
                    id=model_id,
                    label=str(info.get("label") or "OpenRouter key"),
                    suffix=str(info.get("suffix") or "****"),
                    fingerprint=str(info.get("fingerprint") or "unknown"),
                    created_at=str(info.get("created_at"))
                    if info.get("created_at")
                    else None,
                )
            )
        return result

    async def add_key(
        self,
        *,
        key: str,
        label: str,
        model: str,
        model_name: str = DEFAULT_MODEL_ALIAS,
        existing_ids: Collection[str] | None = None,
    ) -> ManagedKey:
        """Register a key in a server-selected LiteLLM deployment pool.

        ``existing_ids`` scopes idempotent duplicate detection to the caller's
        ownership set. Without it, the low-level client keeps its legacy global
        behavior for operational callers; the user-facing API always supplies
        the current user's IDs.
        """
        now = datetime.now(timezone.utc).isoformat()
        key_id = str(uuid4())
        fingerprint = key_fingerprint(key)
        existing = next(
            (
                item
                for item in await self.list_managed()
                if item.fingerprint == fingerprint
                and (existing_ids is None or item.id in existing_ids)
            ),
            None,
        )
        if existing is not None:
            return existing
        payload = {
            "model_name": model_name,
            "litellm_params": {
                "model": model,
                "api_base": OPENROUTER_BASE_URL,
                "api_key": key,
                "headers": self._openrouter_headers,
            },
            "model_info": {
                MANAGED_MARKER: True,
                "managed_key_id": key_id,
                "label": label,
                "suffix": key_suffix(key),
                "fingerprint": fingerprint,
                "created_at": now,
            },
        }
        response = await self._request("POST", "/model/new", json=payload)
        model_id = self._extract_model_id(response)
        if model_id is None:
            registered = await self.list_managed()
            match = next(
                (item for item in registered if item.fingerprint == fingerprint),
                None,
            )
            if match is None:
                raise LiteLLMAdminError("gateway did not confirm key registration")
            model_id = match.id
        return ManagedKey(
            id=model_id,
            label=label,
            suffix=key_suffix(key),
            fingerprint=fingerprint,
            created_at=now,
        )

    async def update_model(self, model: str) -> None:
        """Point every project-managed deployment at one selected upstream model."""
        for item in await self.list_managed():
            await self._request(
                "PATCH",
                f"/model/{validate_model_id(item.id)}/update",
                json={"litellm_params": {"model": model}},
            )

    async def test_key(self, model_id: str) -> bool:
        if model_id not in {item.id for item in await self.list_managed()}:
            raise LiteLLMAdminError("managed key was not found")
        payload = await self._request("GET", "/health", params={"model_id": model_id})
        unhealthy = payload.get("unhealthy_endpoints")
        healthy = payload.get("healthy_endpoints")
        if isinstance(healthy, list) and healthy:
            return True
        if isinstance(unhealthy, list) and unhealthy:
            raise LiteLLMAdminError("invalid_key")
        raise LiteLLMAdminError("unavailable")

    async def delete_key(self, model_id: str) -> None:
        managed = {item.id for item in await self.list_managed()}
        if model_id not in managed:
            raise LiteLLMAdminError("managed key was not found")
        await self._request("POST", "/model/delete", json={"id": model_id})

    async def _request(
        self, method: str, path: str, **kwargs: object
    ) -> dict[str, object]:
        client = self._http_client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
        try:
            response = await client.request(
                method,
                f"{self._base_url}{path}",
                headers={"Authorization": f"Bearer {self._admin_token}"},
                **kwargs,
            )
            if response.status_code >= 400:
                if response.status_code in {401, 403}:
                    reason = "invalid_key"
                elif response.status_code == 429:
                    reason = "rate_limited"
                elif response.status_code >= 500:
                    reason = "unavailable"
                elif response.status_code == 404:
                    reason = "gateway management endpoint was not found"
                else:
                    reason = "gateway management request failed"
                raise LiteLLMAdminError(reason)
            try:
                payload = response.json()
            except ValueError as exc:
                raise LiteLLMAdminError("gateway returned an invalid response") from exc
            if not isinstance(payload, dict):
                return {}
            return payload
        except LiteLLMAdminError:
            raise
        except (httpx.HTTPError, TimeoutError) as exc:
            raise LiteLLMAdminError("gateway is unavailable") from exc
        finally:
            if owns_client:
                await client.aclose()

    @staticmethod
    def _extract_model_id(payload: Mapping[str, object]) -> str | None:
        for key in ("model_id", "id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        data = payload.get("data")
        if isinstance(data, Mapping):
            for key in ("model_id", "id"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value
        return None


def validate_model_id(value: str) -> str:
    """Keep deployment identifiers opaque while rejecting empty path values."""
    if not value.strip() or len(value) > 200:
        raise ValueError("invalid managed key id")
    return value
