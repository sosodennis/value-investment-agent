from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from typing import Final
from uuid import uuid4

import httpx

from src.llm_provider_service.domain.errors import ProviderSettingsError
from src.llm_provider_service.domain.key_metadata import (
    key_fingerprint,
    key_suffix,
    validate_model_id,
)
from src.llm_provider_service.domain.provider_models import ManagedProviderKey
from src.llm_provider_service.domain.routes import DEFAULT_MODEL_ALIAS

MANAGED_MARKER: Final = "value_investment_agent_managed"
OPENROUTER_BASE_URL: Final = "https://openrouter.ai/api/v1"
OPENROUTER_LITELLM_PREFIX: Final = "openrouter/"
_SAFE_KEY_STATUSES = frozenset(
    {
        "untested",
        "healthy",
        "cooldown",
        "invalid_key",
        "unavailable",
        "replacement_grace",
    }
)
_SAFE_KEY_ERRORS = frozenset({"invalid_key", "rate_limited", "unavailable"})


class LiteLLMAdminError(ProviderSettingsError):
    """A sanitized error raised for a failed management operation."""


ManagedLlmKey = ManagedProviderKey


def _to_litellm_model_id(public_model_id: str) -> str:
    """Qualify a raw OpenRouter catalog ID for LiteLLM's OpenRouter provider."""
    return f"{OPENROUTER_LITELLM_PREFIX}{public_model_id}"


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

    async def list_managed(self) -> list[ManagedLlmKey]:
        payload = await self._request("GET", "/model/info")
        models = payload.get("data", payload) if isinstance(payload, Mapping) else []
        if not isinstance(models, list):
            return []

        result: list[ManagedLlmKey] = []
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
                ManagedLlmKey(
                    id=model_id,
                    label=str(info.get("label") or "OpenRouter key"),
                    suffix=str(info.get("suffix") or "****"),
                    fingerprint=str(info.get("fingerprint") or "unknown"),
                    created_at=str(info.get("created_at"))
                    if info.get("created_at")
                    else None,
                    status=(
                        str(info.get("status"))
                        if isinstance(info.get("status"), str)
                        and info.get("status") in _SAFE_KEY_STATUSES
                        else "untested"
                    ),
                    last_tested_at=(
                        str(info.get("last_tested_at"))
                        if info.get("last_tested_at")
                        else None
                    ),
                    failure_count=(
                        int(info.get("failure_count"))
                        if isinstance(info.get("failure_count"), int)
                        and info.get("failure_count") >= 0
                        else 0
                    ),
                    cooldown_until=(
                        str(info.get("cooldown_until"))
                        if info.get("cooldown_until")
                        else None
                    ),
                    last_error=(
                        str(info.get("last_error"))
                        if isinstance(info.get("last_error"), str)
                        and info.get("last_error") in _SAFE_KEY_ERRORS
                        else None
                    ),
                    last_used_at=(
                        str(info.get("last_used_at"))
                        if info.get("last_used_at")
                        else None
                    ),
                    replacement_retire_at=(
                        str(info.get("replacement_retire_at"))
                        if info.get("replacement_retire_at")
                        else None
                    ),
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
    ) -> ManagedLlmKey:
        """Register a key in a server-selected LiteLLM deployment pool.

        ``existing_ids`` scopes idempotent duplicate detection to the caller's
        ownership set. Without it, the low-level client keeps its legacy global
        behavior for operational callers; the user-facing API always supplies
        the current user's IDs.
        """
        now = datetime.now(UTC).isoformat()
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
                "model": _to_litellm_model_id(model),
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
                "status": "healthy",
                "last_tested_at": now,
                "failure_count": 0,
            },
        }
        response = await self._request("POST", "/model/new", json=payload)
        model_id = self._extract_model_id(response)
        if model_id is None:
            registered = await self.list_managed()
            match = next(
                (
                    item
                    for item in registered
                    if item.fingerprint == fingerprint
                    and (existing_ids is None or item.id in existing_ids)
                ),
                None,
            )
            if match is None:
                raise LiteLLMAdminError("gateway did not confirm key registration")
            model_id = match.id
        return ManagedLlmKey(
            id=model_id,
            label=label,
            suffix=key_suffix(key),
            fingerprint=fingerprint,
            created_at=now,
            status="healthy",
            last_tested_at=now,
        )

    async def update_model(self, model: str) -> None:
        """Point every project-managed deployment at one selected upstream model."""
        for item in await self.list_managed():
            await self._request(
                "PATCH",
                f"/model/{validate_model_id(item.id)}/update",
                json={"litellm_params": {"model": _to_litellm_model_id(model)}},
            )

    async def test_key(self, model_id: str) -> bool:
        managed = next(
            (item for item in await self.list_managed() if item.id == model_id),
            None,
        )
        if managed is None:
            raise LiteLLMAdminError("managed key was not found")
        payload = await self._request("GET", "/health", params={"model_id": model_id})
        unhealthy = payload.get("unhealthy_endpoints")
        healthy = payload.get("healthy_endpoints")
        if isinstance(healthy, list) and healthy:
            await self._record_health(
                model_id,
                status="healthy",
                failure_count=0,
                last_error=None,
            )
            return True
        if isinstance(unhealthy, list) and unhealthy:
            await self._record_health(
                model_id,
                status="invalid_key",
                failure_count=managed.failure_count + 1,
                last_error="invalid_key",
            )
            raise LiteLLMAdminError("invalid_key")
        await self._record_health(
            model_id,
            status="unavailable",
            failure_count=managed.failure_count + 1,
            last_error="unavailable",
        )
        raise LiteLLMAdminError("unavailable")

    async def _record_health(
        self,
        model_id: str,
        *,
        status: str,
        failure_count: int,
        last_error: str | None,
    ) -> None:
        await self._update_metadata(
            model_id,
            {
                "status": status,
                "last_tested_at": datetime.now(UTC).isoformat(),
                "failure_count": failure_count,
                "last_error": last_error,
            },
        )

    async def mark_replacement_grace(
        self, model_id: str, *, retire_at: datetime
    ) -> None:
        await self._update_metadata(
            model_id,
            {
                "status": "replacement_grace",
                "replacement_retire_at": retire_at.astimezone(UTC).isoformat(),
            },
        )

    async def cleanup_expired_replacements(self) -> int:
        now = datetime.now(UTC)
        expired = [
            item
            for item in await self.list_managed()
            if item.replacement_retire_at is not None
            and _parse_utc(item.replacement_retire_at) <= now
        ]
        for item in expired:
            await self.delete_key(item.id)
        return len(expired)

    async def _update_metadata(
        self, model_id: str, values: Mapping[str, object]
    ) -> None:
        model_id = validate_model_id(model_id)
        managed = next(
            (item for item in await self.list_managed() if item.id == model_id),
            None,
        )
        if managed is None:
            raise LiteLLMAdminError("managed key was not found")
        await self._request(
            "PATCH",
            f"/model/{model_id}/update",
            json={"model_info": dict(values)},
        )

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
                    reason = "unavailable"
                elif response.status_code == 429:
                    reason = "rate_limited"
                elif response.status_code >= 500:
                    reason = "unavailable"
                elif response.status_code == 404:
                    reason = (
                        "not_found"
                        if method == "POST" and path == "/model/delete"
                        else "unavailable"
                    )
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


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise LiteLLMAdminError("gateway returned invalid lifecycle metadata") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
