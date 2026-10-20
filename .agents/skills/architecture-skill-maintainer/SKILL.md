---
name: architecture-skill-maintainer
description: Reconcile this project's agent skills with implemented architecture after a material architecture change, especially work guided by pstack. Use when agent layer topology, subdomain ownership, workflow or state contracts, runtime boundaries, or cross-agent responsibilities change; skip routine edits that leave those stable.
---

# Architecture Skill Maintainer

Keep the project-specific agent skills accurate as the finance-agent architecture evolves. This skill supplements pstack's general workflows; it does not replace implementation, debugging, or architecture review skills.

## Source of truth

- Use the implemented code and tests to describe observed behavior. Keep observed behavior separate from intended policy.
- Treat `AGENTS.md` as project context and `architecture-standard-enforcer/references/cross-agent-architecture-standard.md` as the canonical hard-rule document.
- A refactor alone does not authorize changing a hard architecture rule. Update the standard only when the architecture decision explicitly changes that rule.

## Workflow

1. Identify the material architecture changes from the current diff and the affected agent modules. If no material change remains, check the three skill entrypoints and report that no update is needed.
2. Compare the changes with each project skill:
   - `agent-implementation-extractor`: keep its paths, state/workflow discovery guidance, and evidence requirements aligned with the codebase.
   - `agent-debug-review-playbook`: keep its boundary, failure, degradation, and validation diagnostics aligned with current agent behavior.
   - `architecture-standard-enforcer`: keep it as the single compliance entrypoint; update its workflow and canonical reference only for approved standard changes.
3. Make the smallest updates that remove stale guidance. Keep each skill's responsibility distinct; do not copy the same architecture rules into multiple skills. Update descriptions or `agents/openai.yaml` only when routing or invocation metadata actually changed.
4. Use `.agent/references/skill-change-request-template.md` for a proposed general hard-rule change. Do not create a new change request for a mechanical correction that directly follows an already-approved architecture decision.
5. Validate every changed skill with `quick_validate.py` when available. Also check referenced paths and links, search for stale paths or retired contracts, and run relevant repository checks if the skill change affects executable behavior. For documentation-only updates, state that code tests were not applicable.

## Completion report

Report the architecture change reviewed, which of the three skills changed or were confirmed current, the validation performed, and any remaining mismatch. Do not claim all skills are current unless each was checked.
