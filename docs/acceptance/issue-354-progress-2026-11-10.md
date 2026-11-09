# Issue #354 Progress

Date: 2026-11-10
Issue: [Workspace] Make Fundamental analysis evidence-first and remove manual valuation setup
Base commit: `6f8eaaff2af2cbeff8e7978cb3cc52b4a4452d74`
Branch: `codex/issue-354-workspace`

## Baseline

- The Workspace exposes `Start analysis`, `Start valuation`, and a required caller-owned valuation assumptions form.
- `Start analysis` sends no `valuation_request`, so the current Agent Core path publishes Fundamental facts-only output.
- Fundamental Service already returns automatic preparation, assumptions evidence, quality status, provenance, and Monte Carlo fields when the caller submits a compact `fundamental.v1` request.
- Valuation approval is currently surfaced in Activity even though Fundamental owns the valuation decision context.

## Planned delivery units

1. Replace the duplicate entry controls and remove the required caller-owned form.
2. Parse and render service-owned preparation, evidence, quality, provenance, and uncertainty in Fundamental.
3. Move approval and supported assumption edits into Fundamental while preserving service-owned calculations and digests.
4. Add focused frontend and browser acceptance evidence.

Status: WIP. Acceptance is not complete, the issue remains open, and no PR has been created.
