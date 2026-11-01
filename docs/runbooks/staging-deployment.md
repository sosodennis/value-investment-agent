# Run the local staging stack

This guide runs the repository's canonical Compose stack with a dedicated
`.env.staging` file and project name. The stack uses local HTTP endpoints and
project-scoped Docker resources. It does not certify hosted TLS, proxy, or
cookie behavior.

## Prepare the staging environment

Provider secret generation, organization-key rotation/revocation, encrypted
storage, and retained-data gates are defined in
[`provider-secret-lifecycle.md`](provider-secret-lifecycle.md). Follow that
runbook before changing either provider encryption key or resetting provider
data.

Run the setup script once from the repository root. Point it at the existing
local environment so it can copy only the four `STAGING_*` values that the
smoke test needs:

```bash
STAGING_SOURCE_ENV_FILE=/absolute/path/to/.env ./scripts/prepare_staging_env.sh
```

The script creates `.env.staging` with mode `0600`. It generates the database
password, internal service tokens, the directory and audit cursor signing
secrets, and Fernet encryption keys. It refuses to overwrite an existing file. Keep the
file on the host and do not commit it.

Check the file mode and ignore rule without printing its contents:

```bash
stat -f '%Lp %N' .env.staging
git check-ignore -v .env.staging
```

If a staging credential or OpenRouter key changes, remove the old staging file
only after stopping the stack and confirming that its database data is
disposable. Run the setup script again with the new source file, then repeat
the full acceptance run.

## Validate and start the stack

Use the `value-investment-agent-staging` project name from `.env.staging` for
every command. The ports in `.env.staging` must be free on the host.

If a port is in use, edit that `*_HOST_PORT` value. Keep all six host ports
unique. Update `STAGING_BASE_URL` when you change `BACKEND_HOST_PORT`, and
update `FRONTEND_ALLOWED_ORIGINS` when you change `FRONTEND_HOST_PORT`.

```bash
PROJECT=value-investment-agent-staging
docker compose --env-file .env.staging -p "$PROJECT" config --quiet
docker compose --env-file .env.staging -p "$PROJECT" up -d --build
```

The default stack contains PostgreSQL, Redis, the backend migration job, the
backend, the LLM provider service, the search service, two model inference
services, and the frontend. The technical labeling scheduler is optional and
starts only with the `scheduler` profile:

```bash
docker compose --env-file .env.staging -p "$PROJECT" --profile scheduler up -d
```

Inspect service state and health without resolving or printing environment
values:

```bash
docker compose --env-file .env.staging -p "$PROJECT" ps
docker compose --env-file .env.staging -p "$PROJECT" ps --format json \
  | jq -r '.[] | [.Service, .State, (.Health // "")] | @tsv'
```

The required services must report `running` and `healthy`. The migration job
must report successful completion. Check the backend directly at its published
Compose port:

```bash
BACKEND_URL="http://$(docker compose --env-file .env.staging -p "$PROJECT" port backend 8000 | sed 's/.*://')"
curl --fail --silent --show-error "$BACKEND_URL/health"
```

## Run staging acceptance

Run the smoke test with the staging secret file and a temporary report path:

```bash
REPORT=/tmp/value-investment-agent-staging-smoke.jsonl
STAGING_KEY_IMPORT_FILE=/absolute/path/to/open-router-api-key.csv \
STAGING_REQUIRE_LIVE_PROVIDER=1 \
STAGING_SECRET_FILE=.env.staging \
STAGING_SMOKE_REPORT="$REPORT" \
bash scripts/refactor_staging_smoke.sh
```

The smoke test checks the backend health endpoint and creates or logs in to the
staging account. With `STAGING_KEY_IMPORT_FILE` set, it imports the whole CSV
as one asynchronous batch, requires every non-empty CSV row to be imported or
reported as a duplicate with no invalid or retryable rows, and tests every
labelled key against the live provider service. It then starts the AAPL
workflow and waits for the required valuation approval checkpoint. The
acceptance run must stop at that checkpoint. Do not approve the valuation and
do not run the deterministic calculation during this infrastructure
acceptance.

Review the report for statuses and request metadata only. It must contain no
raw provider key, password, token, Fernet key, or response body:

```bash
jq -c . "$REPORT"
docker compose --env-file .env.staging -p "$PROJECT" logs --no-color \
  | python3 scripts/check_staging_secret_redaction.py \
      --env-file .env.staging --file .env.staging.example \
      --secret-value-file /absolute/path/to/open-router-api-key.csv \
      --file "$REPORT" --stdin
```

The scan must pass. Record the Compose project name, verified commit, command
exit codes, service health, smoke report path, and known failures in the issue
or acceptance document. Do not paste secret values, cookies, or complete
response bodies into GitHub.

## Stop and clean up

Stop only this staging project. The normal command keeps its named database
and Redis volumes:

```bash
PROJECT=value-investment-agent-staging
docker compose --env-file .env.staging -p "$PROJECT" down
```

Inspect the project and its volumes before deleting data. This local project's
PostgreSQL volume contains only the staging test account, imported provider
keys, workflow runs, and artifacts. Its Redis volume contains staging cache
state. Deleting both removes that data; the checked-out source, `.env.staging`,
and smoke test recreate the stack and its test records. Remove volumes only
when you intend that reset or have a verified backup:

```bash
docker compose --env-file .env.staging -p "$PROJECT" ps -a
docker volume ls --filter "label=com.docker.compose.project=$PROJECT"
docker compose --env-file .env.staging -p "$PROJECT" down --volumes
```

Do not run a global Docker prune command. Keep `.env.staging` until the
staging database is removed and no later run needs its encrypted credentials.

## Maintain this guide

The backend/platform owner maintains this guide. Update it in the same change
that alters any of the following:

- Compose services, profiles, health checks, images, networks, volumes, or
  published ports.
- Required environment variables, generated key types, secret sources, or
  credential rotation procedures.
- The staging smoke endpoints, asynchronous import contract, provider test,
  AAPL workflow, approval checkpoint, or report redaction checks.
- Stop, volume retention, cleanup, or recovery steps.

After each update, rerun environment creation in an isolated disposable
stack, validate the Compose configuration, run the complete staging smoke, and
record the exact commit and results. Treat a failed or incomplete run as
unverified until the guide and the implementation agree.
