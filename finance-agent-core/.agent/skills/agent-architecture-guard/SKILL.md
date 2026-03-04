---
name: agent-architecture-guard
description: Enforce the canonical cross-agent class naming and layer responsibility standard for finance-agent-core/src/agents/*. Use when reviewing PRs, refactoring agent code, creating new agent modules/classes, or auditing architecture regressions in layering, naming semantics, typed runtime boundaries, async behavior, error/state contracts, and structured logging.
---

# Agent Architecture Guard

## Overview

Apply the canonical cross-agent architecture standard consistently across agent code.
Detect violations, propose minimal fixes, and keep migrated slices free of compatibility residue.

## Required Reference

Read `references/cross-agent-architecture-standard.md` before reviewing or editing code.
Treat hard rules as blocking unless the user explicitly requests a temporary exception.

## Workflow

1. Scope the slice.
- Focus on `finance-agent-core/src/agents/*` and directly affected boundary modules.
- Ignore unrelated files unless they create import/runtime coupling risk.

2. Map ownership and layer responsibilities.
- Classify each changed module as `domain`, `application`, `interface`, or `infrastructure`.
- Enforce hard boundaries and reject cross-layer leakage.

3. Enforce naming and packaging contracts.
- Verify class suffix semantics (`*Provider`, `*Repository`, `*Client`, `*Service`, `*Factory`, `*Mapper`, `*Policy`, `*Port`).
- Verify filename-role match (`*_service.py`, `*_provider.py`, etc.).
- Reject generic catch-all modules in mature contexts.

4. Validate runtime/type and async boundaries.
- Reject avoidable `object` types beyond allowed decode/state-entry boundaries.
- Replace long callable bundles with typed runtime ports.
- Ensure async use-cases do not run blocking sync I/O or heavy compute on the event loop.
- Require lifecycle-managed client/session reuse on hot async paths.

5. Validate error/state/logging contracts.
- Keep unified error update shape and resilient state readers.
- Distinguish missing artifact from empty payload.
- Require typed degraded provider outcomes (not bare `None`).
- Require structured start/completion/degraded logs with machine-readable fields.

6. Validate migration hygiene.
- Migrate call sites atomically per slice whenever feasible.
- Remove compatibility shims/aliases immediately after validation.
- Add hygiene guards for removed imports/modules when relevant.

7. Report and remediate.
- Order findings by severity with file+line references and violated rule section.
- Provide the smallest maintainable patch that restores compliance.
- State explicitly when no findings are detected and note residual risk/test gaps.

## Output Requirements

Use this format in reviews/refactor reports:
- `Findings`: prioritized list with rule section references.
- `Assumptions/Open Questions`: only if blockers remain.
- `Applied Changes`: concise summary of concrete edits.
- `Validation`: tests/lint/checks run, or explicit statement if not run.

## Resource

Canonical standard: `references/cross-agent-architecture-standard.md`
