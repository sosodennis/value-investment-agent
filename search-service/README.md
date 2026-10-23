# Search Service

The Search Service is an independently buildable FastAPI capability service.
It exposes the frozen `search.v1` contract documented in
[`../docs/search-service-contract.md`](../docs/search-service-contract.md).

Run locally with:

```sh
cd search-service
uv run uvicorn search_service.app:app --host 0.0.0.0 --port 8003
```

The default application intentionally has no provider registry or durable
control plane. Deployment wiring must inject those ports before readiness is
advertised. Build with `docker compose build search-service`; the image uses
the `internal-contracts` named context for shared `internal.v1` auth/context
primitives.
