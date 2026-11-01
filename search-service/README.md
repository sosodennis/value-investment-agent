# Search Service

The Search Service is an independently buildable FastAPI capability service.
It exposes the frozen `search.v1` contract documented in
[`../docs/search-service-contract.md`](../docs/search-service-contract.md).

Run locally with:

```sh
cd search-service
uv run uvicorn search_service.app:app --host 0.0.0.0 --port 8003
```

The runtime registers DDGS and Tavily adapters. DDGS runs in a bounded worker
pool; timed-out workers retain their slot until they actually finish. Tavily is
enabled by default and sends credentials only in its HTTPS request body.

Provider credentials and preferences use Search-owned PostgreSQL tables. Set
`SEARCH_CONTROL_DATABASE_URL` and `SEARCH_PROVIDER_ENCRYPTION_KEY` to enable
the durable control plane. Generate the Fernet key with:

```sh
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

The target organization schema is versioned as `search_provider_schema_version`
and is created on first use. Legacy `search_provider_*` tables cause startup to
fail so disposable data can be reset explicitly and retained production data
cannot be deleted implicitly. Keep the encryption key stable and back it up
separately; rotate it only with
[`docs/runbooks/provider-secret-lifecycle.md`](../docs/runbooks/provider-secret-lifecycle.md).
In Compose, the service connects to the existing `postgres` service and waits
for its health check. Use a unique Compose project name and host ports for
concurrent worktrees. Build with
`docker compose build search-service`; the image uses the `internal-contracts`
named context for shared `internal.v1` auth/context primitives.
