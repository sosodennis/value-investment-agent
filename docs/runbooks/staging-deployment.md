# Run the local staging stack

This guide runs the repository's canonical Compose stack with a dedicated
`.env.staging` file and project name. The stack uses local HTTP endpoints and
project-scoped Docker resources. It does not certify hosted TLS, proxy, or
cookie behavior.

## Prepare the staging environment

Run the setup script once from the repository root. Point it at the existing
local environment so it can copy only the four `STAGING_*` values that the
smoke test needs:

```bash
STAGING_SOURCE_ENV_FILE=/absolute/path/to/.env ./scripts/prepare_staging_env.sh
```

The script creates `.env.staging` with mode `0600`. It generates the database
password, internal service tokens, and Fernet encryption keys. It refuses to
overwrite an existing file. Keep the file on the host and do not commit it.

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

Use one project name for every command. The ports in `.env.staging` must be
free on the host.

```bash
PROJECT=value-investment-agent-issue198-staging
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

Run the smoke test with the staging secret file and an ignored report path:

```bash
STAGING_SECRET_FILE=.env.staging \
STAGING_SMOKE_REPORT=.audit/issue-198-staging.jsonl \
bash scripts/refactor_staging_smoke.sh
```

The smoke test checks the backend health endpoint, creates or logs in to the
staging account, imports both staging OpenRouter keys, polls asynchronous key
import batches, and tests each stored key against the provider service. It
then starts the AAPL workflow and waits for the required valuation approval
checkpoint. The acceptance run must stop at that checkpoint. Do not approve
the valuation and do not run the deterministic calculation during this
infrastructure acceptance.

Review the report for statuses and request metadata only. It must contain no
raw provider key, password, token, Fernet key, or response body:

```bash
jq -c . .audit/issue-198-staging.jsonl
rg -n '(sk-|Bearer |password|token|Fernet|OPENROUTER)' \
  .audit/issue-198-staging.jsonl
```

The second command must produce no output. Record the Compose project name,
verified commit, command exit codes, service health, smoke report path, and
known failures in the issue or acceptance document. Do not paste secret
values, cookies, or complete response bodies into GitHub.

## Stop and clean up

Stop only this staging project. The normal command keeps its named database
and Redis volumes:

```bash
PROJECT=value-investment-agent-issue198-staging
docker compose --env-file .env.staging -p "$PROJECT" down
```

Inspect the project and its volumes before deleting data. Remove volumes only
when the staging data is disposable or a verified backup exists:

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
