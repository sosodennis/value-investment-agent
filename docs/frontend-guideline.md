# Frontend engineering guide

Date: 2026-10-24 | Status: Canonical | Scope: `frontend/`

This guide defines frontend boundaries, naming, UI foundations, and quality gates. The source tree is being aligned over time. Apply the target rules to new work and migrate existing code when you touch it.

All UI and component recommendations in [Discussion #130](https://github.com/sosodennis/value-investment-agent/discussions/130) are adopted as the product's target design direction. Use its page-by-page recommendations as approved scope for future UI work. Adoption does not mean that a recommended feature or component is already implemented.

## 1. Organize code by feature

- Keep `src/app/` focused on Next.js routes, layouts, and page composition. Put feature behavior in feature-owned modules.
- For new features, group API calls, parsers, view models, hooks, components, and tests under `src/features/<feature>/`. Keep shared primitives in `src/components/ui/` and genuinely cross-feature utilities in `src/lib/`.
- Keep existing paths until a feature change needs them. Move a feature as one reviewable unit and remove its old imports in the same change.
- Treat the frontend as one Next.js application. Do not add another UI kit or split npm packages without a demonstrated ownership or deployment need.
- Keep charts specialized to their job. The current project uses Recharts for general charts and Lightweight Charts for financial price series.

`/workspace` owns Fundamental, Technical, News, and Debate output views. They are workspace views, not separate routes. Keep page routing separate from that domain distinction.

## 2. Parse data at every boundary

Every API, SSE, and artifact path follows this flow:

1. The backend Pydantic schema generates `contracts/openapi.json`.
2. `frontend/src/types/generated/api-contract.ts` contains the generated TypeScript contract.
3. A boundary parser validates runtime data and maps wire fields to named frontend models.
4. A feature adapter creates the view model used by hooks and components.
5. UI components render typed props and view models only.

Feature API modules own the browser paths and target the backend's `/api/v1` public contract. Do not assemble endpoint paths in components. Keep the URL version separate from the generated OpenAPI type names and from internal service contract versions.

Treat `response.json()`, SSE frames, local storage, and artifact payloads as `unknown` until a parser accepts them. Do not cast unvalidated input into a trusted model. Do not add payload parsing, field guessing, or backend-shape fallbacks to a component.

Keep parsers with the feature that owns the payload. Existing shared boundaries include `src/types/protocol.ts`, the agent artifact parsers, and `src/types/agents/output-adapter.ts`. Reuse them when they own the contract; do not create a second parser for the same shape.

The backend wire contract uses `snake_case`. Map it to `camelCase` in the parser when a view model uses TypeScript naming. Generated files are outputs. Edit the OpenAPI source and regenerate them instead of hand-editing generated types.

When a contract changes, update the backend schema, generated OpenAPI, parser, view model, consumer, fixtures, and tests together. Remove obsolete branches after all callers have moved. This project is not yet released, so do not preserve compatibility aliases without an explicit migration need.

## 3. Use the project UI foundation

- Use shadcn/ui as the shared component foundation. Add source-owned primitives under `src/components/ui/` and keep feature-specific combinations in their feature.
- Use shadcn AI Elements patterns for chat, plans, task progress, tool activity, sources, and confirmation when those patterns fit the workflow. Adapt their examples to this project's typed view models and API/SSE contracts.
- Apply the Professional Matte design through semantic tokens. Do not introduce new direct color palettes or component-specific design systems. See [`docs/ui/stitch/DESIGN.md`](ui/stitch/DESIGN.md).
- Use clear semantic tokens for surface, text, border, action, success, warning, and error states. Components must not depend on a particular theme's raw color name.
- Use `BeuiSelect` only while migrating existing code. New option pickers use the shadcn Combobox pattern. Replace the old picker when its feature is next changed.
- Use semantic HTML, visible focus states, and labels for inputs. Formal accessibility audits are not a release gate, but controls must remain usable with a keyboard and understandable from their labels.

Do not copy an entire external component kit into the app. Add only the source components a feature uses, review their dependencies and license, and keep their behavior owned by this repository.

## 4. Name files and values consistently

| Item | Convention | Example |
| --- | --- | --- |
| Folders and source files | `kebab-case` | `search-settings/`, `model-picker.tsx` |
| React components and TypeScript types | `PascalCase` | `SearchSettingsForm`, `SearchProvider` |
| Hooks | `use` plus `PascalCase` | `useSearchSettings` |
| Functions and variables | `camelCase` | `parseSearchSettings` |
| Constants | `UPPER_SNAKE_CASE` for fixed module constants | `MAX_RECONNECT_ATTEMPTS` |
| Routes | URL segments use lowercase kebab-case | `/technical-observability` |
| Wire fields | `snake_case`; map at the parser boundary | `updated_at` to `updatedAt` |

Use names that state the operation and owner. Keep request state separate when operations can fail independently. Prefer `isInitialLoading`, `isRefreshing`, `isSaving`, and `pendingKeyId` over one ambiguous `busy` flag.

## 5. Model UI and request states explicitly

- Give initial load, refresh, submit, delete, and retry distinct state where users can trigger them independently.
- Render loading, empty, partial, error, stale, reconnecting, and completed states from observed data. Do not display a static healthy or synchronized label when the service has not confirmed it.
- Let one failed query remain visible without hiding successful data from another query.
- Keep field errors beside their fields. Show request-level failures with an actionable message and retry action when retry is safe.
- Disable duplicate submissions while a mutation is pending. Preserve the previous successful result when a refresh fails.
- Represent workflow status with a discriminated union when states have different data or allowed actions. Avoid optional-field bags that permit contradictory combinations.

## 6. Keep SSE parsing and recovery in the feature boundary

The supported transport is browser to FastAPI. Do not add a Next.js Route Handler only to proxy SSE. The current fetch-based reader must parse SSE framing before a feature parser validates the event payload.

SSE consumers must:

- validate event identity, run identity, event name, and payload before updating state;
- keep the last applied cursor per active run and ignore duplicate event IDs;
- detect sequence gaps and request replay; if the backend reports `replay_gap`, hydrate `GET /thread/{thread_id}` and resume after the snapshot's cursor;
- reconnect with bounded backoff and stop on unmount, user cancellation, or a terminal event;
- show connection loss and recovery state in the workspace;
- reject events for a different thread or run.

Use `AbortController` to close the reader and release network resources. A browser disconnect stops that subscription, not the server-side run; only the explicit cancel action cancels the run. A process restart can interrupt an active run in the current phase, so the UI must show that state and require an explicit resume. The backend keeps replayable SSE events for 24 hours by default, but this does not define how long run records, checkpoints, or final artifacts remain available.

During local development, test the direct browser-to-FastAPI path. Defer ingress, proxy, and CDN validation until the production path exists. If deployment later requires a Next.js rewrite or proxy, preserve the response stream and status, send `Cache-Control: no-cache, no-transform`, and test the complete path. Durable replay and multi-worker fan-out are backend contract requirements described in [`docs/backend-guideline.md`](backend-guideline.md) and [Discussion #131](https://github.com/sosodennis/value-investment-agent/discussions/131). The frontend implementation is part of [#146](https://github.com/sosodennis/value-investment-agent/issues/146) under the full-stack reset [#143](https://github.com/sosodennis/value-investment-agent/issues/143).

## 7. Run frontend checks

From `frontend/`, run:

```bash
npm run lint
npm run typecheck
npm run test -- --run
```

After a backend API schema change, run `bash scripts/generate-contracts.sh` from the repository root and commit both generated files:

- `contracts/openapi.json`
- `frontend/src/types/generated/api-contract.ts`

Add tests for parser acceptance and rejection, observable UI states, and user actions. Prefer real test primitives and run the application when a change affects browser streaming or interaction behavior.

## 8. Related decisions and sources

- [Discussion #130: frontend architecture and UI foundation](https://github.com/sosodennis/value-investment-agent/discussions/130) records the shadcn/ui decision and feature-level UI analysis.
- [Discussion #131: SSE transport and community cases](https://github.com/sosodennis/value-investment-agent/discussions/131) records the browser-to-FastAPI transport recommendation and probe results.
- [Next.js App Router project structure](https://nextjs.org/docs/app/getting-started/project-structure) describes route and component placement options.
- [shadcn/ui theming](https://ui.shadcn.com/docs/theming) describes semantic CSS tokens.
- [shadcn AI Elements](https://ui.shadcn.com/docs/ai-elements) provides AI interaction patterns.
- [WHATWG Server-sent events](https://html.spec.whatwg.org/multipage/server-sent-events.html) defines event framing, IDs, and reconnect fields.
