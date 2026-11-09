# Issue #355 progress: opt-in forward-evidence reference

Status: WIP checkpoint. This document records the implementation boundary and
the evidence still required before issue acceptance.

## Current state

- Branch: `codex/issue-355-forward-reference`
- Base commit: `e761e13577fb0e50cf611edd0ee2386e90ed360a`
- Normal Fundamental valuation remains the only default path. Search and LLM
  calls are not part of the normal request flow.
- The optional reference will use an explicit Fundamental action route. Agent
  Core owns request orchestration and provider calls; Fundamental Service owns
  claim validation, quality disposition, source/licensing provenance, and
  application of a selected value.

## Checkpoint `10d9ff3c`

This checkpoint records the public-entrypoint and resource-boundary repair on
the exact commit `10d9ff3c` (`checkpoint(#355): enforce fundamental entrypoint
boundaries`). The API now imports the Fundamental public entrypoint; the route
is built from an injected service factory; capability consumers use the
forward-evidence facade; and LLM principal/context access uses the
`llm_provider.entrypoint` contract.

The representative opt-in fixture measured one search query, one retained
discovery result, zero source fetches, one structured LLM call, and a 15,000 ms
request budget. The policy bounds are five results per query, 120,000 source
bytes, eight extracted claims, and 15,000 ms. These are recorded fixture
measurements and a bounded policy, not production enablement approval.

Checks run against `10d9ff3c`:

| Check | Result |
| --- | --- |
| `python3 scripts/architecture_guard.py` | exit 0; no boundary violations |
| `uv run --project finance-agent-core ruff check ...` | exit 0 |
| `PYTHONPATH=finance-agent-core uv run --project finance-agent-core python -c 'from src.agents.fundamental.entrypoint import fundamental_forward_evidence_router; ...'` | exit 0 |
| `PYTHONPATH=finance-agent-core uv run --project finance-agent-core python -c 'import api.server; ...'` | exit 0 |
| Agent Core focused pytest | exit 0; 25 passed |
| Fundamental Service focused pytest | exit 0; 63 passed |
| frontend `npm run typecheck` | exit 0 |
| frontend focused Vitest | exit 0; 28 passed |
| `bash scripts/generate-contracts.sh` | exit 0; generated artifacts synchronized |
| `docker compose --env-file .env.example config --quiet` | exit 0 |
| `git diff --check` and staged commit checks | exit 0 |

Docker service-backed acceptance, real browser interaction, exact-commit CI,
PR review, and merge to `main` remain outstanding. The issue is still WIP and
must not be marked verified or closed.

## Planned contract

1. A reference request identifies the issuer, model, material evidence field,
   and the automatic preparation digest. It is rejected unless the caller has
   explicitly opted in.
2. The response is a separate forward-looking evidence layer. Each numeric
   claim includes the issuer, metric, value, unit, fiscal period, publication
   and retrieval timestamps, source identity, retained passage, content hash,
   extraction method, quality/conflict status, and license metadata.
3. Unsupported, stale, mismatched-period, conflicting, or unlicensed claims
   are excluded or surfaced with a typed reason. Search results and LLM output
   alone are never treated as evidence.
4. Research does not change a valuation. Applying one claim calls the existing
   Fundamental override path with the automatic preparation and a manual
   provenance record that retains the selected reference. A new input digest
   and recalculation are required.

## Checks still required

- Contract and domain tests for valid claims, rejection reasons, conflicts,
  licensing, freshness, and digest-bound application.
- Agent Core tests proving no optional-provider call on the normal path,
  explicit opt-in orchestration, provider failure, and bounded resource use.
- Browser tests for the explicit Fundamental action, evidence display, and
  selected application.
- Isolated Docker/service-backed acceptance with the #355 Compose project,
  followed by exact-commit CI and PR evidence.

## Known limitation

No production provider calls are enabled by default. Resource budgets remain a
measured acceptance item; this checkpoint does not claim #355 is verified.
