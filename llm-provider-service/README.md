# LLM Provider Service

This is the independently deployable LLM capability service. Its public
contract is `internal.v1` plus the project-owned `llm.v1` completion and stream
schemas. Backend agents do not call LiteLLM, OpenRouter, or provider SDKs.

The runtime creates one long-lived LiteLLM Router per process and stores
provider deployments in the service-owned PostgreSQL table with Fernet
encryption. Set a stable `LLM_PROVIDER_ENCRYPTION_KEY` and back it up with the
database. Redis is used for Router cooldown coordination and deployment
revision reconciliation across replicas. There is no alternate provider
runtime or HTTP gateway fallback. Existing keys that remain only in the old
LiteLLM database require the explicit re-key/migration decision tracked by #190.

Run the focused checks with:

```sh
uv run pytest -q
uv run ruff check src tests
```

For Compose, use a unique project name and provide both service secrets:

```sh
export LLM_PROVIDER_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
export LLM_PROVIDER_SERVICE_TOKEN="local-provider-token"
docker compose up -d postgres redis llm-provider-service
```
