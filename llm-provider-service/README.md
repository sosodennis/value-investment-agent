# LLM Provider Service

This is the independently deployable LLM capability service. Its public
contract is `internal.v1` plus the project-owned `llm.v1` completion and stream
schemas. Backend agents do not call LiteLLM, OpenRouter, or provider SDKs.

The runtime stores provider deployments in the service-owned PostgreSQL table
with Fernet encryption. Set a stable `LLM_PROVIDER_ENCRYPTION_KEY` and back it
up with the database. Each request resolves the authenticated user's eligible
deployments, then invokes LiteLLM once for one deployment. The service owns the
shared Redis key-health record: explicit key-scoped failures set a cooldown or
invalid-key status, while model, account, workspace, and upstream-provider
limits never rotate credentials. Retryable model and upstream-provider limits
honor `Retry-After` within the request budget; account and workspace credit
limits remain terminal. The same Redis records are read by the
settings API, so runtime use, failures, cooldown expiry, and safe error
categories remain visible across replicas. A Redis read failure makes data
plane selection fail closed. There is no alternate provider runtime or HTTP
gateway fallback. Existing keys that remain only in the old LiteLLM database
require the explicit re-key/migration decision tracked by #190.

The provider owns one bounded attempt budget per request. Interactive requests
use up to two upstream dispatches and background requests up to three; the
budget covers structured-output correction, backoff, `Retry-After`, and the
monotonic request deadline. LiteLLM Router retries and fallbacks are disabled
so they cannot create hidden attempts. A stream may retry before its first
delta, and returns an explicit interrupted outcome after output begins without
replaying delivered content.

Run the focused checks with:

```sh
uv run pytest -q
uv run ruff check src tests
```

For Compose, use a unique project name and provide both service secrets:

```sh
export LLM_PROVIDER_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
export LLM_PROVIDER_SERVICE_TOKEN="local-provider-token"
docker compose -p value-investment-agent-llm-provider up -d postgres redis llm-provider-service
```
