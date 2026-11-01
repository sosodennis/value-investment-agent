# Engineering documentation

This index separates coding rules from contracts, decisions, research, and operations. Only the two guides below define general frontend and backend coding standards.

Root `AGENTS.md` contains finance-domain constraints, agent skill routing, and repository-specific instructions. It points to these guides for general coding rules.

## Canonical guides

- [Frontend engineering guide](frontend-guideline.md)
- [Frontend UI design guide](frontend-ui-guideline.md) supplements the frontend guide with visual and component rules.
- [Backend engineering guide](backend-guideline.md)
- [Issue and worktree lifecycle](issue-worktree-lifecycle.md) defines parent integration branches, child issue merges, verification, and cleanup.

## Specialized architecture rules

- [Agent Architecture Standard](../.agents/skills/architecture-standard-enforcer/references/cross-agent-architecture-standard.md) defines hard dependency and graph rules for agent work.
- [Cross-agent refactor playbook](../finance-agent-core/docs/standards/refactor_lessons_and_cross_agent_playbook.md) records implementation lessons and review steps. It does not replace the standard.
- [Frontend UI design guide](frontend-ui-guideline.md) describes the product's visual direction and semantic token usage.

## Contracts and service references

- [OpenAPI contract index](../contracts/README.md)
- [LLM Provider contract](llm-provider-contract.md)
- [Model Inference boundary](issue-121-inference-boundary.md)
- [Search Service contract](search-service-contract.md)
- [Internal capability service contract](../finance-agent-core/src/shared/internal_services/README.md)
- Service-specific deployment and operating instructions live in each service README and in [`runbooks/`](runbooks/).
- [`Organization authorization matrix`](runbooks/authorization-matrix.md) defines the server-side role, relationship, and failure contract for organization actions.
- [`Organization lifecycle`](runbooks/organization-lifecycle.md) defines organization and membership operations, status transitions, ownership invariants, lifecycle events, and verification commands.
- [`Notification inbox`](runbooks/notification-inbox.md) defines the durable recipient-private inbox, payload safety, action references, delivery boundary, and verification commands.
- [Local staging deployment](runbooks/staging-deployment.md) defines the dedicated `.env.staging` lifecycle, Compose commands, smoke acceptance, and maintenance rules.

## Decisions and research

- [Discussion #130: frontend architecture and UI foundation](https://github.com/sosodennis/value-investment-agent/discussions/130)
- [Discussion #131: SSE transport and recovery](https://github.com/sosodennis/value-investment-agent/discussions/131)
- [Discussion #140: backend guidelines, module boundaries, and SSE](https://github.com/sosodennis/value-investment-agent/discussions/140)
- Accepted architecture decisions include the [Analysis Workspace runtime durability ADR](analysis-workspace-runtime-durability-adr-2026-03-21.md), its [detailed companion](analysis-workspace-runtime-durability-detailed-adr-2026-03-21.md), and the [observability backbone ADR](technical-decision-observability-backbone-adr-2026-03-21.md).
- Research and audit reports live in [`research-paper/`](research-paper/) and [`reports/`](reports/). Verification scripts write raw benchmark outputs to the ignored root `reports/` directory.

ADRs record decisions for a specific system change. Contracts describe a service or data boundary. Reports record evidence and a dated code review. These references do not create a competing general coding standard.

## Archived documents

- [Root workflow entrypoint migration](archive/root-workflow-entrypoint-migration-2026-10-25.md) records the completed migration and its validation.
- [2026-03 technical strategy proposals](archive/strategy/technical-strategy-master-roadmap.md) and their supporting [quant priorities](archive/strategy/technical-quant-feature-priorities-free-data.md), [calibration roadmap](archive/strategy/calibration-upgrade-roadmap-and-roi.md), and [project advancement report](archive/strategy/project-advancement-report-2026-03.md) are historical proposals, not current project commitments.
