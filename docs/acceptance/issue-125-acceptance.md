# Issue #125 acceptance report

- Base SHA: `cf3d6b952689544fba057dac0e212bea37f8cc08` (#122 merge).
- Implementation SHA: `def17ccca853babb44617699991003ff24147eef`.
- Verdict: PASS for the frozen #122 contract.

## Evidence

- PASS: `cd finance-agent-core && uv run pytest tests/test_search_settings_api.py -q` (`4 passed`). The tests cover authenticated ownership, masked key responses, key-validation error redaction, and service-token forwarding without browser cookies.
- PASS: `cd frontend && pnpm exec vitest run src/app/settings/search/page.test.tsx` (`4 passed`). The tests cover loading and empty states, provider ordering, add-and-test behavior, rejected keys, and service unavailability.
- PASS: `cd frontend && pnpm typecheck`.
- PASS: `cd frontend && pnpm exec eslint src/app/settings/search/page.tsx src/app/settings/search/page.test.tsx src/lib/search-settings-api.ts`.
- PASS: `cd frontend && pnpm build`. The production build includes `/settings/search`.
- PASS: `python3 scripts/architecture_guard.py` and `git diff --check`.
- PASS: commit hooks for whitespace, end-of-file, large files, Ruff, and Ruff format.

## Behavior

The settings page lists provider capabilities, lets the user enable providers and change their priority, and shows masked key metadata. Add and replace send one request to Search Service, which tests the key before saving it. The browser receives only the key suffix and fingerprint. Delete uses the authenticated user's key ID.

The BFF no longer exposes a separate test-only route. That route duplicated validation because Search Service already tests keys during add and replace. The Search Service contract remains unchanged.

## Scope note

The frozen #122 contract and #123 storage schema allow one active key per user and provider. The page supports testing and replacing that key. Same-provider key pools and automatic per-key failover are not part of this implementation and still need a product decision. Provider-priority fallback remains separate.

No live provider credentials or upstream requests were used during acceptance.
