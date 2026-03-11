---
name: agent-implementation-extractor
description: Extract deep architecture and concrete implementation mechanics for agent modules in finance-agent-core/src/agents and future agents. Use when asked to explain package structure, state payloads, LangGraph workflow, tool-action-result details, LLM prompt and structured-output strategy, or cross-agent boundaries with code-grounded evidence.
---

# Agent Implementation Extractor

## Overview
Extract both architecture and implementation details for a target agent module.
Prioritize evidence-backed mechanics over generic summaries.

## Operating Rules
- Ground every major claim in code evidence using `path:line`.
- Label non-trivial statements as `Observed` or `Inferred`.
- Focus on core mechanisms; skip trivial boilerplate.
- Do not skip behavior-shaping reliability logic: retry, backoff, timeout, fallback, idempotency, cache.
- If evidence is missing, write `未在代碼中觀察到` and stop inferring.
- Map architecture as-is first, then note deviations from Domain/Application/Infrastructure/Interface.

## Scope Resolution
1. Resolve target module path: `finance-agent-core/src/agents/<target_agent>/`.
2. If the user does not provide `<target_agent>`, infer from context and state the assumption.
3. If canonical filenames do not exist, use fallback pattern search instead of forcing a filename.

## Discovery Workflow

### Step 1: Structure and State
1. Extract a concise package tree for the target module.
2. Map layer ownership from paths and import direction; highlight root layer vs subdomain layout, vertical-slice boundaries, and shared kernel usage.
3. Identify cross-subdomain orchestration location (root `application/` vs subdomain) and note deviations.
4. Extract state and contract payloads from likely files:
- `interface/types.py`
- `interface/contracts.py`
- `application/state_readers.py`
- `application/state_updates.py`
- `application/dto.py`
4. Record key fields, their meaning, and where they are produced/consumed.

### Step 2: Workflow Graph
1. Read workflow files in this order:
- `subgraph.py`
- `wiring.py`
- `application/orchestrator.py`
2. Build a `stateDiagram-v2` with:
- Nodes and node responsibilities
- Edges and branch conditions
- Parallel fan-out/fan-in if present
3. If no conditional edges exist, explicitly output `No conditional edges observed`.

### Step 3: Deep Implementation Dive
Use Tool-Action-Result for every non-trivial mechanism.
- `Tool/Technique`: library, service, or pattern used.
- `Action`: concrete operation in code.
- `Result`: business or system purpose achieved.
- `Evidence`: `path:line`.

Infrastructure focus:
- Data providers, external APIs, adapters, fetch/parse/normalize pipeline.

Domain focus:
- Policies, scoring, formulas, strategy/model selection, deterministic core math.

Application focus:
- Orchestration, use-case sequencing, concurrency pattern, dependency composition.

### Step 4: LLM Integration Strategy
Scan all prompt and parser related files, including pattern matches:
- `interface/*prompt*`
- `application/*prompt*`
- `interface/parsers.py`
- retry and runtime files (for example `*retry*`, `*prompt_runtime*`)

Extract:
1. Prompt construction strategy:
- Role/persona setup
- Context injection sources
- Constraint and anti-hallucination wording
2. Structured output strategy:
- Pydantic schema or parser used
- `with_structured_output` or equivalent path
3. Reliability controls:
- Retry policy, retryable error predicate, delay/backoff logic
- Validation and parse-failure handling

### Step 5: Boundaries and Dependencies
1. Identify upstream inputs and downstream outputs.
2. Identify cross-agent or kernel dependencies, ports, repositories, and shared contracts.
3. Mark boundary assumptions as `Inferred` unless directly wired in code.
4. Note any legacy path usage or empty layer packages as deviations.

## Boilerplate Filter Policy
- Ignore: simple pass-through logging, generic try/except wrappers, obvious serializer plumbing.
- Keep: logic that changes behavior, output correctness, latency, or determinism.
- Keep by default: retries, fallbacks, parse guards, state merge semantics, branch predicates.

## Fallback Search Playbook
Use these searches when canonical files are absent:

```bash
rg --files finance-agent-core/src/agents/<target_agent>
rg -n "StateGraph|add_node|add_edge|add_conditional_edges|compile" finance-agent-core/src/agents/<target_agent>
rg -n "prompt|with_structured_output|parser|retry|backoff|timeout" finance-agent-core/src/agents/<target_agent>
rg -n "TypedDict|TypeAlias|BaseModel|state_readers|state_updates" finance-agent-core/src/agents/<target_agent>
```

## Output Contract
Return exactly this top-level structure:

1. `Agent Deep Dive: <target agent>`
2. `Architecture and State`
3. `Workflow Graph`
4. `Implementation Deep Dive (Tool-Action-Result)`
5. `LLM and Prompt Strategy`
6. `External Dependencies and Cross-Agent Boundaries`
7. `Deviations, Risks, and Unknowns`

For section details:
- `Architecture and State`: package tree, layer map, state payload fields, key contracts.
- `Workflow Graph`: Mermaid `stateDiagram-v2`, node roles, edge conditions.
- `Implementation Deep Dive`: split into Infrastructure, Domain, Application with evidence.
- `Deviations, Risks, and Unknowns`: mark unknowns explicitly and separate observed facts from inferences.
  - Include legacy path residues and empty layer packages if observed.

## Quality Gate
Pass all checks before final output:
- Every major claim has at least one `path:line` evidence tag.
- No fabricated tools, algorithms, or prompt policies.
- No filler language.
- No forced assumptions about fixed filenames.
- Conditional edges are either described with predicates or explicitly marked absent.
- Unknowns are declared; not patched with speculation.
