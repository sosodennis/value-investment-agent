# Prompt Refactor Guideline (Domain Builder First)
Date: 2026-02-16
Scope: `finance-agent-core/src/agents/*`
Policy: Prompt business semantics belong to `domain`; transport rendering belongs to `interface`.

## 1. Objective

This guideline standardizes prompt ownership for agent systems:

1. Domain owns prompt business logic and constraints.
2. Application owns prompt selection in workflow steps.
3. Interface owns provider/runtime rendering (LangChain/OpenRouter message objects).

This preserves business intent while preventing provider lock-in in domain/application code.

Status Update (2026-02-16):

1. News agent duplicate prompt parser/formatter implementation in `application/` has been removed.
2. News prompt parsing/formatting now uses `interface/parsers.py` and `interface/prompt_renderers.py` as SSOT.
3. Intent agent prompt literals in `application/intent_service.py` have been switched to `intent/domain/prompt_builder.py`.
4. News agent prompt policy has been moved to `news/domain/prompt_builder.py` and workflow now reads domain prompt specs.
5. Debate prompt policy has been moved out of `workflow/nodes/debate/prompts.py` into `debate/domain/prompt_builder.py`.
6. Debate workflow nodes now call a dedicated `debate/application/orchestrator.py` entrypoint; node logic is reduced to routing.
7. Debate orchestrator dependency composition has been moved to `debate/application/factory.py`.
8. Fundamental / Technical / News / Intent workflow dependency composition has been moved from workflow nodes to each agent's `application/factory.py`.
9. Technical interpretation prompt policy has been moved to `technical/domain/prompt_builder.py` and `technical/data/tools/semantic_layer.py` now consumes domain prompt specs.
10. Prompt runtime rendering (`ChatPromptTemplate`) for Intent / News / Technical now lives in each agent's `interface/prompt_renderers.py`.
11. Debate workflow nodes no longer import domain prompt constants directly; debate prompt wiring is centralized in `debate/application/factory.py`.
12. News legacy prompt bridge `news/interface/prompts.py` has been removed.

## 2. Core Rule

Prompt content has two parts and must be split:

1. Business semantics:
   - investment policy
   - extraction constraints
   - failure/guardrail rules
   - belongs to `domain/prompt_builder.py` (and optional `domain/prompt_policies.py`)
2. Transport formatting:
   - `system/user/assistant` runtime message shape
   - chain/provider-specific object adaptation
   - belongs to `interface/prompt_renderers.py`

## 3. Mandatory Naming

Per agent, prompt-related files should follow:

1. `domain/prompt_builder.py`
   - `build_<use_case>_prompt_spec(...)`
2. `domain/prompt_policies.py` (optional)
   - reusable policy constants/rules used by builders
3. `interface/prompt_renderers.py`
   - `render_<provider>_messages(prompt_spec, vars)`
4. `application/orchestrator.py` or `application/*_service.py`
   - selects which spec to use, never hardcodes business prompt rules

Deprecated targets for business rules:

1. inline system/user prompt strings in `application/**`
2. prompt strings in `workflow/nodes/**`
3. duplicated prompt-formatter logic in both `application/` and `interface/`

## 4. PromptSpec Contract (Reference)

The domain builder should return a provider-agnostic spec shape (typed object or TypedDict).

Minimum fields:

1. `id`: stable prompt id for tracing/versioning
2. `messages`: semantic message template list
3. `required_vars`: required runtime variables
4. `constraints`: explicit business guardrails

## 5. Agent-by-Agent Refactor Targets

## 5.1 Intent Agent

Current:

1. Extraction/search system prompt rules are now in `intent/domain/prompt_builder.py`.
2. `application/intent_service.py` consumes prompt builder functions (DONE).
3. Orchestrator dependency composition is now in `intent/application/factory.py` (DONE).

Target:

1. Keep orchestration in `intent/application/orchestrator.py`.
2. If provider adapters diverge, add `intent/interface/prompt_renderers.py`.

## 5.2 News Agent

Current:

1. Prompt parsing/formatting duplication between `application/` and `interface/` has been removed.
2. Selection/analysis prompt policy is now encoded in `news/domain/prompt_builder.py` (DONE).
3. Workflow now reads domain prompt specs and passes them into application orchestration (DONE).
4. Workflow dependency composition is now centralized in `news/application/factory.py` (DONE).

Target:

1. Keep final provider-facing rendering in `news/interface/`.
2. Keep `news/interface/{parsers,prompt_renderers}.py` as SSOT (DONE).

## 5.3 Debate Agent

Current:

1. Prompt business templates and adversarial rules are now in `debate/domain/prompt_builder.py` (DONE).
2. `workflow/nodes/debate/prompts.py` has been removed (DONE).

Target:

1. Keep node-level wiring thin; node should receive rendered messages/config from application/interface.
2. Dedicated debate orchestrator has been introduced; `workflow/nodes/debate/nodes.py` now dispatches orchestrator methods only (DONE).

## 5.4 Technical Agent

Current:

1. Semantic interpretation prompt policy is now in `technical/domain/prompt_builder.py` (DONE).
2. Runtime prompt execution in `technical/data/tools/semantic_layer.py` now reads domain prompt specs (DONE).
3. Workflow dependency composition is now centralized in `technical/application/factory.py` (DONE).

Target:

1. Keep data tools focused on indicator/backtest I/O and math.

## 5.5 Fundamental Agent

Current:

1. Fundamental path is mostly deterministic; prompt usage is limited and fragmented by valuation skills.
2. Workflow dependency composition is now centralized in `fundamental/application/factory.py` (DONE).

Target:

1. For any LLM-assisted selection/explanation step, use the same builder/renderer split.
2. Do not place business prompt policy in workflow node files.

## 6. Migration Sequence

Use this order to reduce risk:

1. Introduce `domain/prompt_builder.py` and tests.
2. Introduce `interface/prompt_renderers.py`.
3. Switch application calls to builder + renderer.
4. Remove legacy inline prompt strings/duplicate formatters.
5. Keep behavior parity with regression tests.

## 7. Quality Gates

1. No prompt business rule literals in `workflow/nodes/**`.
2. No duplicated prompt parser/formatter in both `application/` and `interface/`.
3. Prompt path tests:
   - domain builder tests
   - renderer tests
   - orchestrator integration tests
