# Full-stack refactor map

Status: frozen for #144 on baseline `1f9d0745fa0625684c98506c89d750cb8c98161b`.

This directory is the contract handoff from the ownership inventory to the
#148 activity protocol and then to the #145 backend and #146 frontend workers.
The repository is pre-release. The cutover replaces inaccurate names and
shapes directly; it does not preserve old routes, events, payloads, database
contents, checkpoints, aliases, or fallback parsers.

## Documents

- [Ownership and contract inventory](ownership-and-contract-inventory.md)
  records current evidence, one owner for every capability, and the frozen
  public names.
- [Deletion ledger](deletion-ledger.md) records every relevant legacy route,
  event, state field, module, table, parser, and generated contract action.
- [Issue 144 acceptance](../acceptance/issue-144-acceptance.md) records the
  baseline, commands, guard result, evidence, and remaining gaps.

## Handoff rules

1. #148 owns the `workflow.activity` vocabulary, lifecycle, snapshot/SSE
   fixtures, and the explicit replacement for `internal_progress`.
2. #145 consumes this map and the #148 fixtures. It owns backend runtime,
   normalization, persistence, REST/SSE framing, and generated OpenAPI output.
3. #146 consumes the same fixtures and the generated OpenAPI output. It owns
   feature parsers, view models, reducers, hooks, components, and tests.
4. #147 owns cross-worker delivery, root verification tooling, Compose
   orchestration, and final stale-path scans.

Shared contract artifacts are single-writer files. #145 and #146 may consume
the accepted #148 fixtures but do not edit this directory concurrently.

## Frozen architectural boundaries

```text
Browser
  -> frontend feature route and typed view model
  -> /api/v1 Finance API
  -> Auth, analysis/run runtime, artifact/projection, and observability facets
  -> public agent entrypoints and shared contracts
  -> typed clients for LLM Provider, Model Inference, and Search
```

`api/server.py` remains the composition root only. Agent policy and graph
construction remain inside the owning agent. LangGraph state/checkpoints,
durable workflow activity, SSE transport, and final artifacts are separate
contracts with separate owners and retention policies.
