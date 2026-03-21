# Progress Log

---

## Session Start

- **Date**: 2026-03-21 00:26
- **Task name**: `20260321-phase2-labeling`
- **Task dir**: `.codex-tasks/20260321-technical-decision-observability-epic/tasks/20260321-phase2-labeling/`
- **Spec**: See `SPEC.md`
- **Plan**: See `TODO.csv` (4 milestones)
- **Environment**: Python / Docker Compose / pytest / ruff

---

## Context Recovery Block

- **Current milestone**: COMPLETE
- **Current status**: DONE
- **Last completed**: #4 — Add idempotency provider-degraded and cache-isolation tests
- **Current artifact**: `.codex-tasks/20260321-technical-decision-observability-epic/tasks/20260321-phase2-labeling/TODO.csv`
- **Key context**: Phase 2 now includes the full delayed-labeling spine: raw outcome rules, unresolved-event fetch, worker runtime, labeling-specific market-data policy, one-off command, and dedicated scheduler-container hooks.
- **Known issues**: Repo-wide `finance-agent-core/tests` is still not a reliable green gate because of unrelated baseline failures outside this epic slice.
- **Next action**: Hand off to child task #3 for the DB-backed monitoring read model.

---

## Milestone 1: Define outcome labeling contracts and point-in-time rules

- **Status**: DONE
- **Started**: 01:39
- **Completed**: 02:05
- **What was done**:
  - Added phase-2 domain contracts for `OutcomeLabelingRequest`, `OutcomeLabelingResult`, and `HorizonResolution`.
  - Implemented horizon normalization, maturity checks, raw outcome calculations, and path-window extraction in `outcome_labeling_service.py`.
  - Extended the repository port and SQLAlchemy adapter to fetch unresolved prediction events and append outcome rows idempotently.
  - Added a uniqueness guard on `technical_outcome_paths(event_id, labeling_method_version)`.
  - Added focused tests for horizon resolution, bullish/bearish outcome metrics, unresolved-event query behavior, and append-only insert semantics.
- **Key decisions**:
  - Decision: Keep maturity filtering in domain logic, not in the repository.
  - Reasoning: The architecture standard treats repository adapters as storage gateways only, so maturity semantics belong in the domain/worker layer.
  - Alternatives considered: Letting the repository filter matured events by `as_of_time` was rejected during compliance review.
- **Problems encountered**:
  - Problem: Bearish MFE/MAE semantics were initially calculated using bullish favorable/adverse prices.
  - Resolution: Split excursion price selection by direction multiplier and re-ran focused tests.
  - Retry count: 1
- **Validation**: `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_decision_observability_labeling.py finance-agent-core/tests/test_technical_decision_observability_registry.py finance-agent-core/tests/test_technical_import_hygiene_guard.py -q` -> exit 0; `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/decision_observability finance-agent-core/src/infrastructure/models.py finance-agent-core/tests/test_technical_decision_observability_labeling.py` -> exit 0
- **Files changed**:
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/domain/contracts.py` — added phase-2 labeling contract types
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/domain/outcome_labeling_service.py` — added horizon resolution and raw outcome calculations
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/domain/__init__.py` — exported new labeling helpers
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/__init__.py` — surfaced top-level facade exports
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/application/ports.py` — extended repository contract for labeling
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/infrastructure/repository.py` — added unresolved-event fetch and append-only outcome writes
  - `finance-agent-core/src/infrastructure/models.py` — added uniqueness guard for idempotent outcome writes
  - `finance-agent-core/tests/test_technical_decision_observability_labeling.py` — added focused labeling tests
- **Next step**: Milestone 2 — Implement repository and worker runtime for matured-event labeling

## Milestone 2: Implement repository and worker runtime for matured-event labeling

- **Status**: DONE
- **Started**: 02:05
- **Completed**: 09:01
- **What was done**:
  - Added `OutcomeLabelingBatchResult` orchestration to the runtime service so matured unresolved events can be labeled in batches.
  - Added `TechnicalOutcomeLabelingMarketDataReader` with isolated cache namespace and retry policy, plus `TechnicalOutcomeLabelingWorkerService` as the delayed-labeling runtime facade.
  - Kept maturity filtering in domain logic and let the worker orchestrate repo fetch, market-data reads, raw outcome computation, and append-only inserts.
  - Added focused worker tests for success path, unmatured skip, provider degraded path, and existing-row idempotent skip behavior.
- **Key decisions**:
  - Decision: Keep the market-data runtime policy in the labeling worker adapter instead of expanding the shared market-data provider contract.
  - Reasoning: The ADR calls for agent-local isolation of cache namespace and retry behavior, while preserving the existing provider seam.
  - Alternatives considered: A scheduler-owned provider policy layer was rejected because it would push runtime concerns out of the subdomain boundary.
- **Problems encountered**:
  - Problem: The changed path contained an actual provider bug where `fetch_ohlcv()` referenced an undefined `ticker` variable when resolving splits.
  - Resolution: Replaced that reference with an explicit `yf.Ticker(ticker_symbol).splits` fetch and re-ran changed-path validation.
  - Retry count: 1
- **Validation**: `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_decision_observability_labeling.py finance-agent-core/tests/test_technical_decision_observability_worker.py finance-agent-core/tests/test_technical_decision_observability_registry.py finance-agent-core/tests/test_technical_import_hygiene_guard.py -q` -> exit 0; `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/decision_observability finance-agent-core/src/agents/technical/subdomains/market_data/infrastructure/yahoo_ohlcv_provider.py finance-agent-core/tests/test_technical_decision_observability_labeling.py finance-agent-core/tests/test_technical_decision_observability_worker.py` -> exit 0
- **Files changed**:
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/application/decision_observability_runtime_service.py` — added batch labeling orchestration
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/infrastructure/labeling_worker_service.py` — added labeling-specific reader and worker facade
  - `finance-agent-core/src/agents/technical/subdomains/market_data/infrastructure/yahoo_ohlcv_provider.py` — fixed split lookup bug on the changed path
  - `finance-agent-core/tests/test_technical_decision_observability_worker.py` — added worker runtime coverage
- **Next step**: Milestone 3 — Add scheduler-facing one-off command and container runtime hooks

## Milestone 3: Add scheduler-facing one-off command and container runtime hooks

- **Status**: DONE
- **Started**: 09:01
- **Completed**: 09:01
- **What was done**:
  - Added `run_technical_outcome_labeling.py` as the narrow one-off delayed-labeling entrypoint with `--as-of-time`, `--limit`, and `--labeling-method-version`.
  - Added `technical_outcome_labeling.crontab` as the dedicated `supercronic` schedule file.
  - Updated `entrypoint.sh` so the shared image still boots the API by default but respects an explicit command for the scheduler container.
  - Installed `supercronic` in the Docker image and added a `technical-labeling-scheduler` Compose service behind the `scheduler` profile.
- **Key decisions**:
  - Decision: Use one shared image with command override instead of a second Dockerfile or a long-running in-process Python scheduler loop.
  - Reasoning: This preserves one codebase and one environment model while staying aligned with the ADR's dedicated scheduler-container decision.
  - Alternatives considered: Host cron and in-process Python scheduling were both rejected by the ADR and were not implemented.
- **Problems encountered**:
  - Problem: The original entrypoint always booted uvicorn, which would have broken any scheduler container command override.
  - Resolution: Moved the default-backend exec behind an `$# -gt 0` custom-command branch and validated the shell script syntax.
  - Retry count: 0
- **Validation**: `bash -n finance-agent-core/entrypoint.sh` -> exit 0; `UV_CACHE_DIR=finance-agent-core/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/run_technical_outcome_labeling.py --help` -> exit 0; `docker compose --profile scheduler config --services` -> exit 0
- **Files changed**:
  - `finance-agent-core/scripts/run_technical_outcome_labeling.py` — added one-off delayed-labeling script
  - `finance-agent-core/scripts/technical_outcome_labeling.crontab` — added scheduler crontab
  - `finance-agent-core/entrypoint.sh` — added custom-command override path
  - `finance-agent-core/Dockerfile` — installed `supercronic`
  - `docker-compose.yml` — added dedicated scheduler service under the `scheduler` profile
- **Next step**: Milestone 4 — Add idempotency provider-degraded and cache-isolation tests

## Milestone 4: Add idempotency provider-degraded and cache-isolation tests

- **Status**: DONE
- **Started**: 09:01
- **Completed**: 09:01
- **What was done**:
  - Added coverage for cache namespace and retry forwarding in `TechnicalOutcomeLabelingMarketDataReader`.
  - Added script-level coverage for the one-off command output contract.
  - Consolidated phase-2 validation around focused changed-path pytest and ruff gates.
- **Key decisions**:
  - Decision: Treat the one-off script as part of the delayed-labeling contract and test its JSON summary output directly.
  - Reasoning: The scheduler container only needs a narrow, stable CLI surface, so validating that surface lowers operational risk.
  - Alternatives considered: End-to-end Docker build execution was deferred because it would broaden the slice beyond changed-path validation.
- **Problems encountered**:
  - Problem: `uv run` help validation initially failed under the default user cache path due to sandbox permissions.
  - Resolution: Switched the validation command to a workspace-local `UV_CACHE_DIR`.
  - Retry count: 1
- **Validation**: `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_decision_observability_labeling.py finance-agent-core/tests/test_technical_decision_observability_worker.py finance-agent-core/tests/test_technical_decision_observability_registry.py finance-agent-core/tests/test_technical_import_hygiene_guard.py -q` -> exit 0; `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/decision_observability finance-agent-core/src/agents/technical/subdomains/market_data/infrastructure/yahoo_ohlcv_provider.py finance-agent-core/scripts/run_technical_outcome_labeling.py finance-agent-core/tests/test_technical_decision_observability_labeling.py finance-agent-core/tests/test_technical_decision_observability_worker.py` -> exit 0
- **Files changed**:
  - `finance-agent-core/tests/test_technical_decision_observability_worker.py` — added cache isolation and script output coverage
- **Next step**: Phase 2 complete

## Final Summary

- **Total milestones**: 4
- **Completed**: 4
- **Failed + recovered**: 2
- **External unblock events**: 0
- **Total retries**: 2
- **Files created**: 5
- **Files modified**: 10
- **Key learnings**:
  - Labeling stays cleaner when maturity rules remain in domain code and scheduler concerns stay outside the runtime service.
  - A shared image plus command override is enough to support a dedicated `supercronic` container without introducing a second runtime stack.
- **Recommendations for future tasks**:
  - Keep phase-3 monitoring on DB-backed reads only and avoid coupling it to the scheduler container.
