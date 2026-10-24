"""Probe the internal capability endpoints from the isolated Compose network."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
from datetime import UTC, datetime, timedelta

import httpx


def context(correlation_id: str, *, expired: bool = False) -> dict[str, object]:
    deadline = datetime.now(UTC) + timedelta(seconds=-1 if expired else 20)
    return {
        "principal": {"subject_id": "issue126-probe-user"},
        "correlation_id": correlation_id,
        "contract_version": "internal.v1",
        "deadline_at": deadline.isoformat().replace("+00:00", "Z"),
    }


def addresses(host: str, port: int) -> list[str]:
    values = {
        item[4][0]
        for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if item[0] == socket.AF_INET
    }
    return sorted(values)


async def get_ready(
    client: httpx.AsyncClient, host: str, port: int
) -> dict[str, object]:
    ips = addresses(host, port)
    if len(ips) < 2:
        raise RuntimeError(f"{host} resolved to fewer than two replicas: {ips}")
    statuses: dict[str, int] = {}
    for ip in ips:
        response = await client.get(f"http://{ip}:{port}/readyz")
        statuses[ip] = response.status_code
        if response.status_code != 200:
            raise RuntimeError(f"{host} replica {ip} is not ready: {response.text}")
        body = response.json()
        if (
            body.get("status") != "ready"
            or body.get("contract_version") != "internal.v1"
        ):
            raise RuntimeError(f"{host} replica {ip} returned invalid readiness")
    response = await client.get(f"http://{host}:{port}/readyz")
    if response.status_code != 200:
        raise RuntimeError(f"{host} deployment endpoint is not ready: {response.text}")
    return {"resolved_ips": ips, "replica_statuses": statuses}


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def post(
    client: httpx.AsyncClient,
    host: str,
    port: int,
    route: str,
    token: str,
    body: dict[str, object],
) -> httpx.Response:
    return await client.post(
        f"http://{host}:{port}{route}", headers=headers(token), json=body
    )


def assert_error(response: httpx.Response, expected_status: int, code: str) -> None:
    if response.status_code != expected_status:
        raise RuntimeError(
            f"expected {expected_status} from {response.url}, got "
            f"{response.status_code}: {response.text}"
        )
    body = response.json()
    if body.get("contract_version") != "internal.v1":
        raise RuntimeError(f"missing internal contract version: {body}")
    if body.get("error", {}).get("code") != code:
        raise RuntimeError(f"expected error {code}, got {body}")
    if any(
        secret in response.text
        for secret in ("issue126", "private query", "raw-secret")
    ):
        raise RuntimeError("probe response leaked a probe secret or private input")


async def run(phase: str) -> dict[str, object]:
    llm_token = os.environ["LLM_PROVIDER_SERVICE_TOKEN"]
    search_token = os.environ["SEARCH_SERVICE_TOKEN"]
    inference_token = os.environ["INFERENCE_SERVICE_TOKEN"]
    async with httpx.AsyncClient(timeout=10.0) as client:
        llm_ready = await get_ready(client, "llm-provider-service", 8002)
        search_ready = await get_ready(client, "search-service", 8003)
        news_ready = await get_ready(client, "model-inference-news", 8001)
        fls_ready = await get_ready(client, "model-inference-fls", 8001)

        unauthorized = await client.post(
            "http://search-service:8003/v1/providers/catalog",
            json={"context": context("unauthorized"), "input": {}},
        )
        assert_error(unauthorized, 401, "internal_auth_missing")

        expired_search = await post(
            client,
            "search-service",
            8003,
            "/v1/providers/catalog",
            search_token,
            {"context": context("search-expired", expired=True), "input": {}},
        )
        assert_error(expired_search, 504, "DEADLINE_EXCEEDED")

        expired_inference = await post(
            client,
            "model-inference-news",
            8001,
            "/v1/inference",
            inference_token,
            {
                "context": context("inference-expired", expired=True),
                "schema_version": "inference.v1",
                "operation": "news.sentiment",
                "input": {"text": "A private query must not be logged."},
            },
        )
        assert_error(expired_inference, 504, "DEADLINE_EXCEEDED")

        expired_llm = await post(
            client,
            "llm-provider-service",
            8002,
            "/v1/completions",
            llm_token,
            {
                "context": context("llm-expired", expired=True),
                "input": {
                    "schema_version": "llm.v1",
                    "messages": [{"role": "user", "content": "probe"}],
                    "route": {"alias": "openrouter/free"},
                    "request_id": "issue126-expired",
                    "operation": "issue126",
                    "request_class": "interactive",
                    "temperature": 0.0,
                    "timeout_seconds": 1.0,
                },
            },
        )
        assert_error(expired_llm, 504, "deadline_exceeded")

        settings_write = await post(
            client,
            "search-service",
            8003,
            "/v1/settings/update",
            search_token,
            {
                "context": context("search-settings-write"),
                "input": {
                    "providers": [{"provider": "ddgs", "enabled": True, "priority": 0}]
                },
            },
        )
        if settings_write.status_code != 200:
            raise RuntimeError(f"Search settings write failed: {settings_write.text}")
        settings_read = await post(
            client,
            "search-service",
            8003,
            "/v1/settings/read",
            search_token,
            {"context": context("search-settings-read"), "input": {}},
        )
        if settings_read.status_code != 200:
            raise RuntimeError(f"Search settings read failed: {settings_read.text}")
        providers = settings_read.json()["result"]["settings"]["providers"]
        if (
            len(providers) != 1
            or providers[0]["provider"] != "ddgs"
            or not providers[0]["enabled"]
            or providers[0]["priority"] != 0
        ):
            raise RuntimeError(f"Search settings did not persist: {providers}")

        return {
            "phase": phase,
            "llm": llm_ready,
            "search": search_ready,
            "model_inference_news": news_ready,
            "model_inference_fls": fls_ready,
            "checks": {
                "authentication": "pass",
                "deadline_errors": "pass",
                "redaction": "pass",
                "search_settings_write_read": "pass",
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.phase)), sort_keys=True))


if __name__ == "__main__":
    main()
