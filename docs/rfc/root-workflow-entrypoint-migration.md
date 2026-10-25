# Root workflow entrypoint migration

## Problem

The root workflow composes five agent graphs through temporary `application/subgraph.py` bridges and initializes the Postgres checkpointer in the same function that assembles graph topology. Three public entrypoints require injected dependencies, so root cannot yet use those public contracts. The migration must preserve the existing fan-out, join, debate handoff, interrupt response, and OpenAPI schema while removing the bridges and old root-node adapters.

## Usage

Production calls each agent entrypoint to build its graph with its own default wiring. Tests inject runners into agent entrypoints and prebuilt fake graphs into root composition.

```python
root_builder = build_root_graph(
    RootAgentGraphs(
        intent=build_intent_extraction_graph(),
        fundamental=build_fundamental_subgraph(),
        news=build_financial_news_subgraph(),
        technical=build_technical_subgraph(),
        debate=build_debate_subgraph(),
    )
)
root_graph = root_builder.compile(checkpointer=checkpointer)
```

```python
news_graph = build_financial_news_subgraph(fake_news_runner)
```

## Shape

`RootAgentGraphs` is a frozen, named bundle of the five compiled child graphs. Each public agent builder accepts its existing typed runner or ports; when omitted, it lazily asks that same agent's `application.wiring` for defaults. Root composition imports only these public entrypoints and shared root state. It builds and returns `StateGraph[AgentState]` without environment reads, provider construction, logging setup, or database access.

`get_graph()` owns production graph construction and Postgres saver lifecycle. It obtains the default child graphs through the public entrypoints, calls the pure root composer, and compiles with the configured saver. Root tests compile the same composition without a saver and use fake child graphs to verify state handoff and debate routing.

Intent owns the public ticker-selection interrupt contract under its interface package and exports it from the public entrypoint. The API imports that contract from the entrypoint. The model fields and serialized payload remain unchanged.

## Synthesis decision

Candidate A is the base: one builder per agent with optional typed injection, agent-owned defaults, a named bundle, and pure root topology construction. Candidate B's separate default-builder names were rejected because they create a second graph-building API for the same capability. The cross-judge (gpt-6-astra) scored A higher for call-site simplicity, boundary ownership, testability, and avoiding duplicate APIs. Its recommendation to test root invocation and merged research state is included.

No separate alternative was grafted. Candidate B's explicit non-null builder parameter was considered, but its clarity did not justify five extra public functions while the same dependency remains injectable through one typed API.

## Tradeoffs

- The public builder uses `None` to select agent-owned defaults, keeping one graph-building function for production and tests.
- The named five-graph bundle repeats root capability membership, making omissions visible at construction and review.
- Root topology remains under `src/workflow`; each agent owns its graph, runners, and default wiring.
- The root keeps its existing Postgres lifecycle and graph metadata to limit behavior change.

## Alternatives

- Separate `build_default_*` and injected builders make production intent explicit but double the public graph-building API across all five agents.
- Root importing `application.wiring` would expose private adapter construction and violate the public entrypoint boundary.
- Keeping compatibility bridges would preserve two ways to build each graph and retain obsolete architecture exceptions.

## Implementation

The root composer preserves the existing node names, metadata, reducers, and edge topology. `get_graph()` owns default child graph construction and the Postgres saver lifecycle. Each public agent builder selects its own wiring when no runner or ports are injected. At the time of this migration, the API imported `InterruptValue` from the intent entrypoint; the #147 cutover replaces that message contract with a runtime-owned typed activity interruption.

All in-repository callers now use agent-owned workflow builders. The five `application/subgraph.py` bridges, the obsolete root node wrappers, and their guard exceptions have been removed. Issue #37 owns the generated action report and regenerates it after this migration lands.

## Risks

The repository cannot show whether consumers outside the checkout import the removed compatibility modules. In-repository imports are clean. External callers must move to the public agent entrypoints or workflow contracts.

## Validation

The root composition test invokes fake agent graphs and checks that their merged research state reaches debate. Agent entrypoint tests inject fake runners and verify graph input and output schemas.

The focused root, interrupt, and agent entrypoint suite passed 16 tests. Migrated intent, news, and debate workflow tests passed 21 tests. The news application use-case and error tests passed 29 tests. The architecture guard passed with 12 unrelated legacy edges remaining. The generated OpenAPI schema matched `contracts/openapi.json` across all 11 paths.

The full suite reported 863 passed, 5 skipped, and 8 failed after the final news state assertions were migrated. Seven artifact-manager tests fail without a database service. One workspace projection test expects `financial_news_research` but receives `None`. These failures do not involve the root composition migration.
