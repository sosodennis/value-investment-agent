# Environment configuration reference

This page classifies the environment keys used by the root Compose files, the
verification overlays, `.env.example`, and `.env.staging.example`. Use the
classification before editing an env file. Do not invent values for keys that
refer to external credentials or pinned SEC assets.

## Choose the configuration path

| Path | Start with | Add | Gate |
| --- | --- | --- | --- |
| Local application | `.env.example` copied to `.env` | A generated LLM Fernet key. Keep the local service defaults unless you need a separate stack. | `docker compose config --quiet` |
| Isolated issue acceptance | A worktree-local `.env` with unique ports | The exact service tokens, SEC assets, and paths required by the issue manifest. | `ACCEPTANCE_MANIFEST=... scripts/acceptance_preflight.sh` |
| Staging | `.env` as the source for disposable account values | `scripts/prepare_staging_env.sh`, which generates the staging secrets and ports. | `docs/runbooks/staging-deployment.md` |
| Production | Deployment secret manager | Production-only service secrets and encryption keys. | `docker-compose.production.yml` and the deployment checks |

The acceptance manifest records the env-file path and its SHA-256. The
preflight rejects shell-only overrides, changed env files, missing required
values, missing SEC assets, and stale ports.

## Generate locally owned values

Generate a Fernet key with this command:

```sh
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Use the output for one of these keys:

| Key | Owner | Rule |
| --- | --- | --- |
| `LLM_PROVIDER_ENCRYPTION_KEY` | Embedded LLM provider | Keep it stable while encrypted provider keys remain in PostgreSQL. |
| `SEARCH_PROVIDER_ENCRYPTION_KEY` | Search service | Keep it stable while encrypted Search provider keys remain in PostgreSQL. |

Generate disposable service tokens and local secret values with
`openssl rand -hex 32`:

| Keys | Owner | Rule |
| --- | --- | --- |
| `INFERENCE_SERVICE_TOKEN` | Backend and inference services | Use the same value in the backend and both inference containers. |
| `LLM_PROVIDER_SERVICE_TOKEN` | Backend and LLM provider | Use the same value at both service boundaries. |
| `SEARCH_SERVICE_TOKEN` | Backend and Search service | Use the same value at both service boundaries. |
| `FUNDAMENTAL_SERVICE_TOKEN` | Backend and Fundamental service | Use the same value in the app overlay and Fundamental service. |
| `DIRECTORY_CURSOR_SECRET`, `AUDIT_CURSOR_SECRET` | Backend | Use a unique value per environment. |
| `POSTGRES_PASSWORD` | PostgreSQL | Generate a value for staging or production. The local example uses a disposable default. |
| `REDIS_PASSWORD` | Redis | Leave empty for the local default or generate a value when Redis authentication is enabled. |

The staging generator creates the generated values and writes `.env.staging`
with mode `0600`. It copies only the disposable staging account values from
the source `.env`.

## Provide external values

These values come from a person, an external provider, or a deployment
operator. Do not generate placeholders and call them valid.

| Keys | Source | Rule |
| --- | --- | --- |
| `FUNDAMENTAL_SEC_USER_AGENT` | Application owner | Use an identifiable application name and a monitored contact. The example value is a placeholder and fails SEC acceptance. |
| `FRED_API_KEY` | FRED | Optional for the core local stack. Add it only when a FRED-backed path is enabled. |
| `STAGING_EMAIL`, `STAGING_PASSWORD` | Disposable staging account | The staging generator copies these from the source `.env`. Never use a personal production account. |
| `STAGING_OPENROUTER_KEY`, `STAGING_SECONDARY_OPENROUTER_KEY` | OpenRouter | Optional staging credentials. Keep them in the ignored env file. |
| OpenRouter user keys | App LLM settings | Add them in the application settings page. Do not put them in Compose or source files. |
| `OPENROUTER_HTTP_REFERER`, `OPENROUTER_X_TITLE` | Application owner | Optional request metadata. Use a real application identity when configured. |

## Pin SEC evidence assets

The SEC verification overlay needs four host mounts and four digests. The
paths point to reviewed, immutable assets. The digests prove that the mounted
assets match the approved inputs.

| Keys | Meaning | How to set them |
| --- | --- | --- |
| `FUNDAMENTAL_SEC_TAXONOMY_CACHE_HOST_DIR`, `FUNDAMENTAL_SEC_EDGAR_PLUGIN_HOST_DIR`, `FUNDAMENTAL_SEC_XULE_PLUGIN_HOST_DIR` | Host directories mounted read-only into the Fundamental service | Obtain the approved offline bundles for the target parser release. Use absolute paths in the worktree runtime manifest. |
| `FUNDAMENTAL_SEC_DQC_RULESET_HOST_PATH` | Host path to the pinned DQC ruleset file | Obtain the approved ruleset file. Use an absolute path in the runtime manifest. |
| `FUNDAMENTAL_SEC_TAXONOMY_CACHE_SHA256`, `FUNDAMENTAL_SEC_EDGAR_PLUGIN_SHA256`, `FUNDAMENTAL_SEC_XULE_PLUGIN_SHA256` | Directory digests | Compute them with the Fundamental service `_directory_hash` algorithm. That algorithm includes relative file names and bytes and ignores `__pycache__`, `.pyc`, and `.pyo` files. |
| `FUNDAMENTAL_SEC_DQC_RULESET_SHA256` | DQC ruleset file digest | Compute `shasum -a 256 <path>` or `sha256sum <path>` on the exact mounted file. |

The directory hash is not the hash of a tar archive and must not be replaced
with a random SHA-256 string. Run the hash calculation with the Fundamental
service environment so that the result uses the same repository algorithm:

```sh
uv run --directory fundamental-service python - <<'PY'
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, "src")
from fundamental_service.arelle_parser import _directory_hash

for name, raw in (
    ("FUNDAMENTAL_SEC_TAXONOMY_CACHE_HOST_DIR", "<taxonomy-cache-dir>"),
    ("FUNDAMENTAL_SEC_EDGAR_PLUGIN_HOST_DIR", "<edgar-plugin-dir>"),
    ("FUNDAMENTAL_SEC_XULE_PLUGIN_HOST_DIR", "<xule-plugin-dir>"),
):
    print(f"{name}={_directory_hash(Path(raw))}")

dqc = Path("<dqc-ruleset-path>")
print(f"FUNDAMENTAL_SEC_DQC_RULESET_SHA256={hashlib.sha256(dqc.read_bytes()).hexdigest()}")
PY
```

Replace the four placeholders before running the command. Record the resulting
values in the worktree `.env` and rerun the acceptance preflight.

## Set SEC policy and runtime limits

These keys select the accepted SEC evidence and bound resource use. They are
policy inputs, not secrets.

| Keys | Default or source | Rule |
| --- | --- | --- |
| `FUNDAMENTAL_SEC_TAXONOMY_MANIFEST_ID`, `FUNDAMENTAL_SEC_TAXONOMY_VERSION` | Compose defaults | Change only when the approved taxonomy bundle changes. |
| `FUNDAMENTAL_SEC_SUPPORTED_FILING_YEARS`, `FUNDAMENTAL_SEC_SUPPORTED_FILING_FORMS` | Compose defaults | Keep them aligned with the captured evidence cohort. |
| `FUNDAMENTAL_SEC_PARSER_MAX_MEMORY_BYTES`, `FUNDAMENTAL_SEC_PARSER_MAX_CONCURRENCY` | Compose defaults | Increase only with measured resource evidence. |
| `FUNDAMENTAL_SERVICE_INGESTION_ORGANIZATIONS`, `FUNDAMENTAL_SERVICE_INGESTION_RATE_LIMIT_PER_MINUTE`, `FUNDAMENTAL_SERVICE_MAX_INGESTION_MS` | Compose defaults | Set the allowed organizations and bounded SEC acquisition budget. |
| `FUNDAMENTAL_SERVICE_MAX_CALCULATION_SAMPLES`, `FUNDAMENTAL_SERVICE_MAX_REQUEST_MS` | Compose defaults | Keep deterministic calculation and request budgets bounded. |
| `FUNDAMENTAL_SERVICE_RELEASE_ACTIVATION_ORGANIZATIONS`, `FUNDAMENTAL_SERVICE_RELEASE_PUBLISH_ORGANIZATIONS` | Compose defaults | Set the organization policy for release activation and publication. |
| `FUNDAMENTAL_SERVICE_MEMORY_LIMIT` | Compose default | Increase only when the host can support the larger cgroup limit. |

## Choose ports and service locations

Use a unique tuple for every active worktree. Do not copy ports from another
runtime tuple.

| Keys | Meaning |
| --- | --- |
| `COMPOSE_PROJECT_NAME` | Compose project identity for a stack. |
| `BACKEND_HOST_PORT`, `FRONTEND_HOST_PORT`, `POSTGRES_HOST_PORT`, `REDIS_HOST_PORT` | Root application stack host ports. |
| `LLM_PROVIDER_SERVICE_HOST_PORT`, `SEARCH_SERVICE_HOST_PORT` | Root provider service host ports. |
| `FUNDAMENTAL_POSTGRES_HOST_PORT`, `FUNDAMENTAL_SERVICE_HOST_PORT` | Fundamental verification stack host ports. |
| `FRONTEND_ALLOWED_ORIGINS`, `STAGING_BASE_URL` | URLs derived from the selected frontend or backend ports. |
| `FUNDAMENTAL_SERVICE_URL` | Backend-to-Fundamental service location for the app overlay. |
| `LLM_PROVIDER_SERVICE_URL`, `SEARCH_SERVICE_URL`, `MODEL_INFERENCE_FLS_URL`, `MODEL_INFERENCE_NEWS_URL`, `NEXT_PUBLIC_LANGGRAPH_URL` | Internal service locations. Change them only when the Compose topology changes. |

## Keep defaults unless the task requires a change

These keys control optional providers, model selection, local behavior, and
resource limits. The Compose files provide safe local defaults.

| Keys |
| --- |
| `APP_ENV`, `BAKE_HF_MODELS`, `BAKE_INFERENCE_MODELS`, `INFERENCE_ALLOW_INSECURE`, `INFERENCE_CPUS`, `INFERENCE_MEMORY_LIMIT`, `INFERENCE_MEMORY_RESERVATION`, `INFERENCE_TORCH_NUM_THREADS` |
| `CLIENT_DEBUG_CAPTURE_ENABLED`, `CLIENT_DEBUG_CAPTURE_TTL_SECONDS`, `CLIENT_DEBUG_MAX_BYTES_PER_CAPTURE`, `CLIENT_DEBUG_MAX_CAPTURES`, `CLIENT_DEBUG_MAX_CAPTURES_PER_OWNER`, `CLIENT_DEBUG_MAX_EVENTS_PER_CAPTURE`, `CLIENT_DEBUG_MAX_EVENTS_PER_OWNER_PER_MINUTE`, `CLIENT_DEBUG_MAX_EVENTS_PER_REQUEST`, `CLIENT_DEBUG_MAX_TOTAL_BYTES`, `NEXT_PUBLIC_ENABLE_CLIENT_DEBUG_CAPTURE` |
| `LLM_PROVIDER_KEY_COOLDOWN_SECONDS`, `NEWS_FINBERT_MODEL`, `NEWS_FINBERT_REVISION`, `SEC_FLS_MODEL`, `SEC_FLS_REVISION`, `TAVILY_API_ENABLED` |
| `MODEL_INFERENCE_FLS_URL`, `MODEL_INFERENCE_NEWS_URL`, `REDIS_HOST`, `REDIS_PORT`, `POSTGRES_USER`, `POSTGRES_DB`, `LLM_PROVIDER_SERVICE_URL`, `SEARCH_SERVICE_URL` |
| `ORG_DIRECTORY_SEARCH_PER_USER_PER_MINUTE`, `ORG_EXPIRED_NOTIFICATION_RETENTION_DAYS`, `ORG_INVITATIONS_PER_ACTOR_PER_HOUR`, `ORG_INVITATIONS_PER_ORGANIZATION_PER_HOUR`, `ORG_INVITATIONS_PER_RECIPIENT_PER_HOUR`, `ORG_INVITATION_RESENDS_PER_INVITATION_PER_HOUR`, `ORG_ROLE_CHANGES_PER_ACTOR_PER_HOUR`, `ORG_ROLE_CHANGES_PER_ORGANIZATION_PER_HOUR`, `ORG_NOTIFICATION_FANOUT_PER_ORGANIZATION_PER_MINUTE`, `ORG_NOTIFICATION_FANOUT_SYSTEM_PER_MINUTE`, `ORG_NOTIFICATION_RETENTION_DAYS` |
| `ISSUE109_BACKEND_IMAGE`, `ISSUE126_BACKEND_IMAGE`, `ISSUE126_FLS_BASE_IMAGE`, `ISSUE126_FLS_IMAGE`, `ISSUE126_NEWS_BASE_IMAGE`, `ISSUE126_NEWS_IMAGE`, `ISSUE189_POSTGRES_TEST_PORT` |

The last row is for historical verification harnesses. Do not add those keys
to a normal application `.env` unless you are running the matching harness.

## Complete key index

The index below is checked by `scripts/validate_configuration_reference.py`.
When a Compose interpolation or env-example assignment adds a key, add the key
to a classification table and this index in the same change. The validator
also requires every indexed key to have an active Compose, script, or service
consumer. A key that exists only in an example is not a supported setting.

<!-- begin-config-key-index -->
- `APP_ENV`
- `AUDIT_CURSOR_SECRET`
- `BACKEND_HOST_PORT`
- `BAKE_HF_MODELS`
- `BAKE_INFERENCE_MODELS`
- `CLIENT_DEBUG_CAPTURE_ENABLED`
- `CLIENT_DEBUG_CAPTURE_TTL_SECONDS`
- `CLIENT_DEBUG_MAX_BYTES_PER_CAPTURE`
- `CLIENT_DEBUG_MAX_CAPTURES`
- `CLIENT_DEBUG_MAX_CAPTURES_PER_OWNER`
- `CLIENT_DEBUG_MAX_EVENTS_PER_CAPTURE`
- `CLIENT_DEBUG_MAX_EVENTS_PER_OWNER_PER_MINUTE`
- `CLIENT_DEBUG_MAX_EVENTS_PER_REQUEST`
- `CLIENT_DEBUG_MAX_TOTAL_BYTES`
- `COMPOSE_PROJECT_NAME`
- `DIRECTORY_CURSOR_SECRET`
- `FRED_API_KEY`
- `FRONTEND_ALLOWED_ORIGINS`
- `FRONTEND_HOST_PORT`
- `FUNDAMENTAL_DATA_RELEASE_TRUST_ROOTS_HOST_FILE`
- `FUNDAMENTAL_MODEL_TRUST_ROOTS_HOST_FILE`
- `FUNDAMENTAL_POSTGRES_HOST_PORT`
- `FUNDAMENTAL_SEC_DQC_RULESET_HOST_PATH`
- `FUNDAMENTAL_SEC_DQC_RULESET_SHA256`
- `FUNDAMENTAL_SEC_EDGAR_PLUGIN_HOST_DIR`
- `FUNDAMENTAL_SEC_EDGAR_PLUGIN_SHA256`
- `FUNDAMENTAL_SEC_PARSER_MAX_CONCURRENCY`
- `FUNDAMENTAL_SEC_PARSER_MAX_MEMORY_BYTES`
- `FUNDAMENTAL_SEC_SUPPORTED_FILING_FORMS`
- `FUNDAMENTAL_SEC_SUPPORTED_FILING_YEARS`
- `FUNDAMENTAL_SEC_TAXONOMY_CACHE_HOST_DIR`
- `FUNDAMENTAL_SEC_TAXONOMY_CACHE_SHA256`
- `FUNDAMENTAL_SEC_TAXONOMY_MANIFEST_ID`
- `FUNDAMENTAL_SEC_TAXONOMY_VERSION`
- `FUNDAMENTAL_SEC_USER_AGENT`
- `FUNDAMENTAL_SEC_XULE_PLUGIN_HOST_DIR`
- `FUNDAMENTAL_SEC_XULE_PLUGIN_SHA256`
- `FUNDAMENTAL_SERVICE_HOST_PORT`
- `FUNDAMENTAL_SERVICE_INGESTION_ORGANIZATIONS`
- `FUNDAMENTAL_SERVICE_INGESTION_RATE_LIMIT_PER_MINUTE`
- `FUNDAMENTAL_SERVICE_MAX_CALCULATION_SAMPLES`
- `FUNDAMENTAL_SERVICE_MAX_INGESTION_MS`
- `FUNDAMENTAL_SERVICE_MAX_REQUEST_MS`
- `FUNDAMENTAL_SERVICE_MEMORY_LIMIT`
- `FUNDAMENTAL_SERVICE_RELEASE_ACTIVATION_ORGANIZATIONS`
- `FUNDAMENTAL_SERVICE_RELEASE_PUBLISH_ORGANIZATIONS`
- `FUNDAMENTAL_SERVICE_TOKEN`
- `FUNDAMENTAL_SERVICE_URL`
- `INFERENCE_ALLOW_INSECURE`
- `INFERENCE_CPUS`
- `INFERENCE_MEMORY_LIMIT`
- `INFERENCE_MEMORY_RESERVATION`
- `INFERENCE_SERVICE_TOKEN`
- `INFERENCE_TORCH_NUM_THREADS`
- `ISSUE109_BACKEND_IMAGE`
- `ISSUE126_BACKEND_IMAGE`
- `ISSUE126_FLS_BASE_IMAGE`
- `ISSUE126_FLS_IMAGE`
- `ISSUE126_NEWS_BASE_IMAGE`
- `ISSUE126_NEWS_IMAGE`
- `ISSUE189_POSTGRES_TEST_PORT`
- `LLM_PROVIDER_ENCRYPTION_KEY`
- `LLM_PROVIDER_KEY_COOLDOWN_SECONDS`
- `LLM_PROVIDER_SERVICE_HOST_PORT`
- `LLM_PROVIDER_SERVICE_TOKEN`
- `LLM_PROVIDER_SERVICE_URL`
- `MODEL_INFERENCE_FLS_URL`
- `MODEL_INFERENCE_NEWS_URL`
- `NEWS_FINBERT_MODEL`
- `NEWS_FINBERT_REVISION`
- `NEXT_PUBLIC_ENABLE_CLIENT_DEBUG_CAPTURE`
- `NEXT_PUBLIC_LANGGRAPH_URL`
- `OPENROUTER_HTTP_REFERER`
- `OPENROUTER_X_TITLE`
- `ORG_DIRECTORY_SEARCH_PER_USER_PER_MINUTE`
- `ORG_EXPIRED_NOTIFICATION_RETENTION_DAYS`
- `ORG_INVITATIONS_PER_ACTOR_PER_HOUR`
- `ORG_INVITATIONS_PER_ORGANIZATION_PER_HOUR`
- `ORG_INVITATIONS_PER_RECIPIENT_PER_HOUR`
- `ORG_INVITATION_RESENDS_PER_INVITATION_PER_HOUR`
- `ORG_NOTIFICATION_FANOUT_PER_ORGANIZATION_PER_MINUTE`
- `ORG_NOTIFICATION_FANOUT_SYSTEM_PER_MINUTE`
- `ORG_NOTIFICATION_RETENTION_DAYS`
- `ORG_ROLE_CHANGES_PER_ACTOR_PER_HOUR`
- `ORG_ROLE_CHANGES_PER_ORGANIZATION_PER_HOUR`
- `POSTGRES_DB`
- `POSTGRES_HOST_PORT`
- `POSTGRES_PASSWORD`
- `POSTGRES_USER`
- `REDIS_HOST`
- `REDIS_HOST_PORT`
- `REDIS_PASSWORD`
- `REDIS_PORT`
- `SEARCH_PROVIDER_ENCRYPTION_KEY`
- `SEARCH_SERVICE_HOST_PORT`
- `SEARCH_SERVICE_TOKEN`
- `SEARCH_SERVICE_URL`
- `SEC_FLS_MODEL`
- `SEC_FLS_REVISION`
- `STAGING_BASE_URL`
- `STAGING_EMAIL`
- `STAGING_OPENROUTER_KEY`
- `STAGING_PASSWORD`
- `STAGING_PRIMARY_LABEL`
- `STAGING_SECONDARY_LABEL`
- `STAGING_SECONDARY_OPENROUTER_KEY`
- `TAVILY_API_ENABLED`
<!-- end-config-key-index -->
