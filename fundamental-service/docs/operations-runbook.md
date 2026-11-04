# Fundamental Service Operations Runbook

This runbook is subordinate to the [Fundamental enterprise-grade target
state](fundamental-enterprise-grade-target-state.md). It describes the runtime
controls for issue #280 and does not change the data, calculation, provenance,
or release policies defined there.

## Start and health

Run only the isolated verification service from the repository root:

```sh
docker compose -p value-investment-agent-270-integration \
  -f compose/verification/docker-compose.issue280-operations.yml up -d --build
docker compose -p value-investment-agent-270-integration \
  -f compose/verification/docker-compose.issue280-operations.yml ps
```

The default host port is `18080`; set `FUNDAMENTAL_SERVICE_HOST_PORT` when the
port is occupied. `/livez` is process liveness and stays free of dependency
details. `/readyz` is dependency readiness and requires the filesystem snapshot,
content, and artifact stores plus the service token. Both endpoints return only
the `internal.v1` status shape.

Every `/v1/` operation requires `Authorization: Bearer <FUNDAMENTAL_SERVICE_TOKEN>`
and a signed `internal.v1` context in the `{context, input}` body envelope. The
context binds the `fundamental-service` audience, `finance-agent-core` issuer,
principal organization and membership, correlation ID, and absolute deadline.
Error responses use the shared `InternalErrorResponse`; they never include
credentials, provider responses, filesystem paths, or raw filing content.

## Recovery checks

- A missing snapshot or artifact returns `SOURCE_UNAVAILABLE` or a stable
  not-found code. The caller receives an unavailable/degraded result and must
  not calculate locally.
- Restarting the container reopens the append-only artifact record log. Reset
  only the operational cache; retain evidence artifacts and their source
  dependencies. Rebuild a damaged artifact as a new content-addressed
  generation and preserve the old record for audit.
- Disk exhaustion is an operator alert. Stop ingestion, preserve evidence, and
  repair or expand the mounted data volume before publishing another snapshot.
  Do not delete referenced evidence.
- A request over the synchronous sample, forecast, body, rate, or deadline
  budget returns a stable error. There is no server-side job queue.

Inspect `/metrics` for source health, snapshot freshness, cache hit/miss/stale,
calculation latency and budget failures, quality status, abstention,
provenance/replay failures, and provider degradation counters. Metrics are
process diagnostics only and do not replace release evidence or calibration
reports.

## Stop and clean up

```sh
docker compose -p value-investment-agent-270-integration \
  -f compose/verification/docker-compose.issue280-operations.yml down
```

Keep the named volume unless the issue's disposable verification data has been
recorded and a rebuild from captured public snapshots is available. Never use a
global Docker prune command for this service.
