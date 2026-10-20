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
- Map the implemented architecture first, then distinguish it from the target in `architecture-standard-enforcer/references/cross-agent-architecture-standard.md`.
- Treat `entrypoint.py`, agent-owned `workflow/`, `application/`, `domain/`, and optional `capabilities/` as target paths. Report `subdomains/`, root `src/workflow/nodes/<agent>/`, and `application/subgraph.py` as migration-era paths when present.

## Scope Resolution
1. Resolve target module path: `finance-agent-core/src/agents/<target_agent>/`.
2. If the user does not provide `<target_agent>`, infer from context and state the assumption.
3. If canonical filenames do not exist, use fallback pattern search instead of forcing a filename.

## Discovery Workflow

### Step 1: Structure and State
1. Extract a concise package tree for the target module.
2. Map ownership and imports across the agent entrypoint, workflow, application, domain, capabilities, infrastructure, and shared contracts. Label legacy placement explicitly. Graph construction and node adapters belong to the agent's `workflow/`; `application/subgraph.py` is only a temporary caller bridge during root composition migration.
3. Identify which package owns the agent graph and any nested capability graph. Do not assume root-level workflow code owns agent state.
4. Extract state and contract payloads from files that exist, such as `workflow/state.py`, `workflow/*state*.py`, application state readers/writers, and boundary schemas.
5. Record key fields, their meaning, and where they are produced and consumed.

### Step 2: Workflow Graph
1. Start with `entrypoint.py` and the agent's `workflow/` package (state, nodes, and graph builder). Follow an injected runner into application composition as needed.
2. If those paths do not exist, trace the implemented legacy path: `application/subgraph.py`, `application/wiring.py`, and `src/workflow/nodes/<agent>/` including its state module.
3. Read application orchestrators and state readers/writers after locating the graph boundary.
4. Build a `stateDiagram-v2` with:
- Nodes and node responsibilities
- Edges and branch conditions
- Parallel fan-out/fan-in if present
5. If no conditional edges exist, explicitly output `No conditional edges observed`.

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
2. Identify cross-agent imports, capability facade usage, ports, repositories, and shared contracts.
3. Mark boundary assumptions as `Inferred` unless directly wired in code.
4. Check capability edges for private imports and cycles with `python3 scripts/architecture_guard.py`; use the module action report to explain existing exceptions.
5. Note legacy paths and empty packages as observed deviations, not proof that the target architecture is implemented.

## Boilerplate Filter Policy
- Ignore: simple pass-through logging, generic try/except wrappers, obvious serializer plumbing.
- Keep: logic that changes behavior, output correctness, latency, or determinism.
- Keep by default: retries, fallbacks, parse guards, state merge semantics, branch predicates.

## Fallback Search Playbook
Use these searches when canonical files are absent:

```bash
rg --files finance-agent-core/src/agents/<target_agent>
rg -n "StateGraph|add_node|add_edge|add_conditional_edges|compile" finance-agent-core/src/agents/<target_agent> finance-agent-core/src/workflow/nodes
rg -n "prompt|with_structured_output|parser|retry|backoff|timeout" finance-agent-core/src/agents/<target_agent>
rg -n "TypedDict|TypeAlias|BaseModel|state_readers|state_updates" finance-agent-core/src/agents/<target_agent>
rg -n "from src\.agents\.|import src\.agents\." finance-agent-core/src/agents/<target_agent> finance-agent-core/src/workflow
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
