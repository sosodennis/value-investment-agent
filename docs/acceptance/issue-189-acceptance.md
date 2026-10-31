# Issue 189 acceptance evidence

Verified implementation commit: `cf93bab12194731acca6e58e643cfc1cd7a4917e`.
The verified provider image is `linux/arm64` digest
`sha256:b9302890451a6e033f5fa9d0f32eb4f8b906717bdb28daab9500078bac92bb58`.

## Changes

- Pin both Docker stages to the multi-platform `python:3.11-slim` index digest
  `sha256:673719e071ecf27434fd2635bbd8d00f49f4fdd81f243143438a42ced8bedf60`.
- Use `uv==0.13.6` only in the build stage and copy the isolated application
  environment into the runtime stage.
- Upgrade `cryptography` to `50.0.2` and pin the reviewed `filelock==4.2.5`
  security fix. LiteLLM `1.106.6` has not widened its filelock upper bound;
  the override remains until it does.
- Add issue-specific Compose overlays. The real-upstream project publishes no
  host ports, stores PostgreSQL and Redis state only in tmpfs, and uses a
  non-internal network. The database-test project uses a separate tmpfs
  PostgreSQL container and localhost port `15591`.

## Automated verification

Run from `llm-provider-service/`:

| Command | Result |
| --- | --- |
| `.venv/bin/pytest -q` | 59 passed, 5 PostgreSQL tests skipped |
| `RUN_LLM_PROVIDER_POSTGRES_TESTS=1 POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=15591 POSTGRES_DB=langgraph POSTGRES_USER=... POSTGRES_PASSWORD=... .venv/bin/pytest -q` | 64 passed, including PostgreSQL integration tests |
| `.venv/bin/ruff check src tests` | Passed |
| `.venv/bin/ruff format --check src tests` | Passed |
| `uv lock --check` | Passed |

The PostgreSQL-enabled command used credentials from the local, untracked
verification environment. No credential values are recorded here.

## Compose and real OpenRouter acceptance

The disposable two-replica project was
`value-investment-agent-issue-189-security`. Its Compose inputs were
`docker-compose.yml`, `docker-compose.override.yml`, and
`compose/verification/docker-compose.issue189-acceptance.yml`.

- `docker compose ... config --quiet` passed. The resolved test topology had
  no published ports, tmpfs at `/var/lib/postgresql/data` and `/data`, and
  `internal: false` for outbound OpenRouter access.
- Both provider replicas, PostgreSQL, and Redis reported healthy. The two
  provider replicas used the verified image digest above.
- The user-supplied CSV at `~/Downloads/open-router-api-key.csv` was streamed
  over stdin to the service; it was not mounted into a container or copied to
  the repository. The batch completed with 5 imported, 0 duplicate, 0
  invalid, and 0 retryable items. Each key validation used one attempt.
- The importing tenant listed 5 keys; an unrelated tenant listed 0. The second
  replica also listed the importing tenant's 5 keys.
- `nvidia/nemotron-3.5-lightning:free` returned the expected non-empty response
  through each replica. Each completion used one upstream attempt and reported
  `$0` cost.
- A live OpenRouter shared-pool 429 was classified as `rate_limited`; it did
  not mark the credential invalid or rotate keys. Deterministic fault tests
  cover key-scoped 429 rotation, global 429 non-rotation, 401/402, 5xx,
  timeout, total attempt limits, and stream interruption without replay.
- A synthetic key-scoped cooldown written through replica 1 was read by replica
  2 as `cooldown` / `rate_limited`. After expiry it read as `available`, and
  the synthetic Redis record was deleted.
- Pausing Redis made a completion return HTTP 504 `deadline_exceeded`. After
  unpausing Redis, it returned healthy.
- Disconnecting PostgreSQL from the isolated Compose network made key listing
  return HTTP 504 `deadline_exceeded`. After reconnecting it, both provider
  replicas listed all 5 keys and all four services returned healthy. The
  PostgreSQL container remained running, so its tmpfs data stayed intact.
- After dependency recovery, a later live inference probe returned upstream
  `upstream_unavailable`. The successful one-attempt inference through both
  replicas above was recorded before fault injection.
- A scan of both provider replica logs found zero matches for the five raw
  provider keys or the temporary service secrets.

## SBOM and CVE review

Docker Scout CLI `1.23.1` scanned the exact image digest above for `linux/arm64`.
The SBOM indexed 231 packages and reported 51 CVE records across 17 packages:
0 critical, 1 high, 1 medium, and 49 low. `docker scout cves --only-fixed`
reported no fixable vulnerable packages. The runtime SBOM does not contain the
build-stage `uv` installer.

The only high finding is Scout's `CVE-2026-85091` match for Debian package
`zlib 1:1.3.dfsg+really1.3.1-1+b1`. The CVE advisory identifies upstream zlib
`1.3.1.2` through `1.3.2` as affected; the image contains upstream zlib
`1.3.1`, so this finding is not affected. Sources: [OSV advisory]
(https://api.osv.dev/v1/vulns/CVE-2026-85091) and the Debian package version in
the verified image.

The medium `CVE-2025-45582` tar finding is marked disputed by the upstream GNU
tar project and requires two crafted archive extractions to overwrite a file.
The Provider Service does not extract user-supplied tar archives. The remaining
49 findings are low severity. These dispositions are recorded for reviewer
assessment; the Scout database itself still reports the findings.

## Remaining gate

The repository has no configured GitHub deployment environment or recorded
deployment. This evidence is from the local, isolated Compose project and real
OpenRouter upstream. It does not claim to be staging evidence. The live 429 was
an upstream shared-pool limit; a real key-scoped upstream fault was not
available, although deterministic tests cover that classification and
rotation path.

Issue #189 explicitly requires staging evidence against the delivered commit.
Keep the issue open and do not mark it `VERIFIED` until that staging evidence
is recorded or the maintainer explicitly revises the criterion.
