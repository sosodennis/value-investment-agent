# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Upgrade the Technical overview UI/UX so the current raw confidence-like value no longer misleads users as a calibrated probability.
- Prioritize backend semantic hardening first so raw fusion magnitude, adjusted signal strength, calibration status, and setup reliability become deterministic report-level concepts.
- Preserve `Direction` as the primary market-state output while separating internal signal magnitude from user-facing setup reliance.
- Add deterministic report-level summaries that frontend can consume directly for enterprise-safe presentation.
- Keep the change additive and compatible with the existing technical report, evidence, quality, and observability surfaces.

## Non-Goals

- Build or ship a true calibrated confidence probability system.
- Build the long-term calibration dataset / fitting / monitoring pipeline.
- Introduce new market data dependencies.
- Remove raw confidence fields from backend artifacts.
- Redesign the entire Technical UI layout.

## Constraints

- Preserve root topology: `application / domain / interface / subdomains`.
- Do not add compatibility shims.
- Backend semantic hardening should be sequenced before frontend wording/layout changes.
- Do not turn the current raw field into an implied probability.
- Allow limited backend deterministic semantics upgrades around raw/effective strength and confidence eligibility, but do not implement full empirical calibration.
- Backend projection semantics belong in root `application`.
- Boundary DTOs and serializers belong in `interface`.
- Frontend wording and rendering logic belong in frontend presentation/facade code.

## Environment

- **Project root**: `/Users/denniswong/Desktop/Project/value-investment-agent`
- **Language/runtime**: Python + TypeScript/React
- **Package manager**: `uv` + frontend workspace tooling
- **Test framework**: `pytest` + Vitest
- **Build command**: targeted backend tests, `ruff check`, frontend tests, `typecheck`, and API contract sync

## Risk Assessment

- [x] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [x] Large file generation — disk space sufficient?
- [x] Long-running tests — timeout configured?

## Deliverables

- Additive backend semantic fields for raw/effective signal strength and confidence eligibility.
- Additive report-level `signal_strength_summary` contract.
- Additive report-level `setup_reliability_summary` contract.
- Deterministic backend logic that derives these summaries from existing raw confidence, quality, degraded, observability, and conflict signals.
- Frontend parser/type alignment and overview UI migration from `Confidence` to `Signal Strength` plus `Setup Reliability`.
- Regression tests covering uncalibrated/degraded/high-raw-strength cases.

## Done-When

- [ ] Backend no longer relies on a single raw `confidence` semantic for consumer-facing meaning.
- [ ] Technical overview no longer presents the current raw value as primary `Confidence`.
- [ ] Backend emits deterministic raw/effective strength and confidence-eligibility semantics suitable for enterprise-safe consumption.
- [ ] Backend full report exposes deterministic `signal_strength_summary` and `setup_reliability_summary`.
- [ ] Frontend renders `Direction`, `Risk Level`, `Setup Reliability`, and `Signal Strength` with non-misleading semantics.
- [ ] Raw confidence and calibration details remain available in deeper inspection surfaces.
- [ ] Targeted backend/frontend validations and lint checks pass.

## Final Validation Command

```bash
uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_regime_and_fusion.py finance-agent-core/tests/test_technical_application_use_cases.py finance-agent-core/tests/test_technical_interface_serializers.py -q && uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/signal_fusion/application/fusion_runtime_service.py finance-agent-core/src/agents/technical/application/use_cases/run_fusion_compute_use_case.py finance-agent-core/src/agents/technical/application/technical_report_projection_service.py finance-agent-core/src/agents/technical/interface/contracts.py finance-agent-core/src/agents/technical/interface/serializers.py finance-agent-core/tests/test_technical_regime_and_fusion.py finance-agent-core/tests/test_technical_application_use_cases.py finance-agent-core/tests/test_technical_interface_serializers.py && npm --prefix frontend run test -- src/components/agent-outputs/TechnicalAnalysisOutput.test.tsx src/types/agents/artifact-parsers.test.ts && npm --prefix frontend run typecheck && npm --prefix frontend run sync:api-contract
```

## Demo Flow (optional)

1. Open a Technical report where raw fusion strength is high but calibration is not applied.
2. Confirm backend report semantics expose raw/effective strength, confidence eligibility, and setup reliability.
3. Confirm the overview shows `Signal Strength` and `Setup Reliability`, not a standalone primary `Confidence` probability.
4. Confirm degraded/conflict/calibration context is surfaced in user-facing reliability messaging.
