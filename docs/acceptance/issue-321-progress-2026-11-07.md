# Issue 321 acceptance evidence

This record covers the immutable release activation work on branch
`codex/issue-321-zero-downtime-release`.

## Identity

- Issue: #321
- Pull request: not opened at this checkpoint
- Base: `origin/main` at `4727b9194bd50825869b4737e47daeb109cbd41f`
- Current synchronization checkpoint: `f900b973` (merge of the issue branch
  with the latest `origin/main`)
- Current verification checkpoint: `c4769479` (tests and static checks below
  were rerun at this exact commit)
- Release trust-root fixture SHA-256:
  `98d739b587416a41f2dd9efab04f83e244c7fc303cff64d8152041e44dbfeb34`
- Canary runner source SHA-256:
  `59309c4bc990ff1b9f5de93efd07e07fbd58c212c31097575927b8c79a726b90`

## Automated checks

### Current synchronization checkpoint

At `c4769479`, the following command exited 0:

```text
uv run pytest tests/test_release_runner.py tests/test_api.py tests/test_replay.py tests/test_data_release_attestations.py
58 passed, 1 existing Starlette/httpx deprecation warning
```

The Compose configuration also passed `docker compose ... config --quiet` for
the dedicated project `value-investment-agent-321-release-verify`.

At the same synchronized source tree, the PostgreSQL release persistence suite
also exited 0:

```text
FUNDAMENTAL_TEST_DATABASE_URL=postgresql+asyncpg://fundamental:fundamental@127.0.0.1:18631/fundamental uv run pytest tests/test_postgres_metadata.py
17 passed, 1 existing Starlette/httpx deprecation warning
```

The dedicated PostgreSQL and Fundamental service containers reported healthy
status. The service image currently running in this project is not yet treated
as final exact-head evidence; it will be rebuilt after the remaining source
changes and its digest recorded below.

At `c4769479`, the repository's pinned pre-commit configuration also passed on
all changed Python files (including Ruff `v0.3.0`), and these checks exited 0:

```text
python -m compileall -q fundamental-service/src fundamental-service/tests
git diff --check
```

The remaining checks must be rerun against the final issue commit before a PR
is opened. The older results below are retained as historical checkpoints and
are not being reused as exact-head acceptance evidence.

### Historical checkpoint

The following commands were run at the code checkpoint. Each command exited 0.

```text
uv run pytest tests/test_release_runner.py tests/test_api.py tests/test_replay.py
52 passed, 1 existing Starlette/httpx deprecation warning

FUNDAMENTAL_TEST_DATABASE_URL=postgresql+asyncpg://fundamental:fundamental@127.0.0.1:18631/fundamental uv run pytest tests/test_postgres_metadata.py
17 passed, 1 existing Starlette/httpx deprecation warning

uv run --with ruff ruff check src/fundamental_service/release_runner.py tests/test_release_runner.py tests/test_postgres_metadata.py
uv run --with ruff ruff format --check src/fundamental_service/release_runner.py tests/test_release_runner.py tests/test_postgres_metadata.py
python -m compileall -q src/fundamental_service/release_runner.py tests/test_release_runner.py
git diff --check
```

The release runner tests cover a signed candidate, raw artifact hash failure,
point-in-time fact mismatch, stable canary digest, and the absence of any
activation operation in the runner. PostgreSQL tests cover CAS fencing,
idempotent activation, competing publishers, audit failure rollback, candidate
transaction rollback after manifest persistence, close/restart recovery, and a
reader overlapping activation.

## Docker environment

The dedicated Compose project is
`value-investment-agent-321-release-verify`. It uses host ports 18091 and
18631. The exact validation command was:

```text
COMPOSE_PROJECT_NAME=value-investment-agent-321-release-verify FUNDAMENTAL_POSTGRES_HOST_PORT=18631 FUNDAMENTAL_SERVICE_HOST_PORT=18091 docker compose -f compose/verification/docker-compose.issue280-operations.yml config --quiet
```

The project was rebuilt from the code checkpoint with:

```text
COMPOSE_PROJECT_NAME=value-investment-agent-321-release-verify FUNDAMENTAL_POSTGRES_HOST_PORT=18631 FUNDAMENTAL_SERVICE_HOST_PORT=18091 docker compose -f compose/verification/docker-compose.issue280-operations.yml up -d --build fundamental-service
```

The service image digest is
`sha256:aa2196b11ae2f5299b124b0205944d1115bf8de7f1d9b6e914e11f658155431f`.
The PostgreSQL image digest is
`sha256:c54a696c68013b2f8f42f479e00a2b6ad24c5ef10ee31cdfb8972cec3dad7eb7`.
Both containers were healthy. `/readyz` returned HTTP 200 with
`{"contract_version":"internal.v1","status":"ready"}`.

An earlier probe against the pre-rebuild service image returned 404 for every
release route. The stale image was not counted as acceptance evidence. The
image was rebuilt and the OpenAPI route set was checked before the successful
probe.

## Live release lifecycle probe

The probe inserted two uniquely named, signed candidates into the dedicated
verification PostgreSQL database, then used the real Fundamental HTTP routes.
It did not delete data or touch another Compose project.

For profile `live-321-e0916fd05dca4f448bd00cf5c5280a27`:

- First manifest digest:
  `490f1558357546e6ea4d11099157dfa5a1ec8e0541a9832c6f5c7e306ffea819`.
- Second manifest digest:
  `e46f1f5ed14188e07676f38ef914de67ea6babc14a9b08cce61276da8c51a509`.
- Initial read returned 404 because no release was active.
- Activate returned 200 in 17.28 ms.
- A stale compare-and-swap returned 409 with
  `DATA_RELEASE_POINTER_CONFLICT`.
- The second activation returned 200 in 9.89 ms.
- Rollback returned 200 in 10.65 ms.
- Thirty-two concurrent active-pointer reads returned only HTTP 200 and one
  complete manifest digest. The slowest read was 63.49 ms.

A retry with the same command ID but a new correlation ID returned
`DATA_RELEASE_IDEMPOTENCY_CONFLICT`, as designed because the audit record binds
the correlation ID. A retry with the same command and the same correlation ID
returned 200 and revision 1 in the controlled probe below.

## Controlled soak probe

For profile `live-321-soak-9c5a3a5df0d74882845c11d645eb0060`, the lifecycle probe
used the same correlation ID for its repeated activation. Activate, repeat,
second activation, and rollback returned 200. The repeated activation returned
revision 1 without a second pointer revision.

The service process was restarted between measurements to clear its in-process
rate limiter. This restart is test setup and is not zero-downtime evidence.
The controlled reader workload stayed below the configured default
`FUNDAMENTAL_SERVICE_RATE_LIMIT_PER_MINUTE=120`:

- Duration: 5 seconds.
- Workers: 2.
- Requests: 46.
- Availability: 1.0.
- Status codes: HTTP 200 only.
- p50: 16.99 ms.
- p95: not reported because the sample had fewer than 100 requests.
- Maximum: 24.13 ms.

An intentionally unconstrained 8-worker probe produced HTTP 200/429 and 1.289%
successful responses. That result is retained as rate-limit behavior and does
not support an unconstrained availability claim.

## Acceptance mapping

- Immutable candidate manifest, signed verification, CAS activation, rollback,
  cache namespace isolation, and request-level release pinning: covered by the
  code checkpoint tests.
- Failed candidate persistence, audit failure, restart recovery, competing
  publishers, and legacy reader overlap: covered by the PostgreSQL suite.
- Read-only canary validation: covered by `DataReleaseCanaryRunner` and its
  replayable report digest. The runner is invoked outside API request handling
  and has no pointer mutation method.
- Docker health and real HTTP release lifecycle: covered by the live probe.
- Load measurement: the controlled probe reports availability and latency
  within the configured rate limit. The unconstrained result is a known limit.

## Remaining verification limits

- A rolling deployment with two different application binaries was not run.
  The additive migration and legacy-reader overlap tests pass, but a live
  two-image rollout still needs deployment infrastructure.
- The live lifecycle probe used metadata candidates without source snapshots
  and facts. Snapshot resolution and in-flight request pinning remain covered
  by the service and cache tests, not by this HTTP probe.
- No production deployment, external load generator, or multi-minute soak was
  run. No release SLO beyond the local rate-limit and latency observations is
  claimed.
