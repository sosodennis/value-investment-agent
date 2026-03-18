# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Upgrade technical LLM interpretation to produce a beginner-friendly plain-language summary plus concise signal explanations.
- Expand `AnalystPerspectiveModel` schema in an additive, enterprise-safe way so explanation fields are structured rather than packed into one summary string.
- Introduce a maintainable explainer input surface so future indicators/signals can be added without rewriting the prompt core.
- Keep deterministic direction/risk/confidence as the source of truth and preserve current guardrail expectations.

## Non-Goals

- Rebuild semantic/fusion policy.
- Create a separate interpretation subdomain or shared kernel.
- Turn technical interpretation into execution advice or a long educational tutorial.
- Add compatibility shims or temporary alias contracts.

## Constraints

- Preserve root topology: `application / domain / interface / subdomains`.
- Prompt specs and structured-output contracts belong in `interface`.
- Input assembly/orchestration belongs in `application`.
- Guardrails remain in `subdomains/interpretation/domain`.
- Frontend/API consumer changes must ship in the same slice as schema/output changes.

## Environment

- **Project root**: `/Users/denniswong/Desktop/Project/value-investment-agent`
- **Language/runtime**: Python + TypeScript/React
- **Package manager**: `uv` + frontend workspace tooling
- **Test framework**: `pytest` + frontend parser tests
- **Build command**: targeted `pytest`, `ruff check`, frontend parser tests as needed
- **Existing test count**: targeted suites only for this task

## Risk Assessment

- [x] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [x] Large file generation — disk space sufficient?
- [x] Long-running tests — timeout configured?

## Deliverables

- Additive schema upgrade for `AnalystPerspectiveModel`.
- Deterministic explainer context assembly for beginner-friendly interpretation.
- Updated interpretation prompt/provider/guardrail behavior for plain-language output.
- Updated backend/frontend consumers and tests.

## Done-When

- [ ] Technical interpretation outputs a concise plain-language summary and structured signal explainers.
- [ ] New explanation fields are present in backend contracts and consumed by frontend parsers/types.
- [ ] Prompt/input architecture supports future indicator additions via explainer metadata instead of prompt rewrites.
- [ ] Targeted backend/frontend validations and lint checks pass.

## Final Validation Command

```bash
uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_application_use_cases.py -q && uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/application finance-agent-core/src/agents/technical/interface finance-agent-core/src/agents/technical/subdomains/interpretation finance-agent-core/tests/test_technical_application_use_cases.py
```

## Demo Flow (optional)

1. Trigger a technical analysis artifact with analyst perspective present.
2. Confirm the report exposes beginner-friendly summary plus concise signal explanations.
3. Verify frontend renders the new explanation content without regressing existing stance/validation sections.
