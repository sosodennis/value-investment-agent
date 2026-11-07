# Issue 336 progress checkpoint

This record is a work-in-progress checkpoint. It is not an acceptance or VERIFIED record.

## Identity

- Issue: #336, blocker for #325
- Branch: `codex/issue-336-issuer-identity`
- Base: `origin/main` at `55608191c13ad02a8efddc7079c54c71c702d8dc`
- Code checkpoint tested: `d789069e28057494068d3a09f52586b55c955e2b`
- Pull request: none
- CI: none

## Checks at the code checkpoint

All commands exited 0.

- `cd fundamental-service && uv run pytest tests/test_sec_source.py tests/test_issuer_identity.py tests/test_identity_resolution_api.py -q`: 31 passed.
- `cd fundamental-service && uv run pytest -q`: 225 passed, 25 skipped, and one Pydantic serializer warning in `test_unverified_quality_refuses_calculation`.
- `cd finance-agent-core && uv run pytest tests/agents/fundamental -q`: 40 passed, with four dependency deprecation warnings from `edgartools`.
- `cd finance-agent-core && uv run ruff check src/agents/fundamental/application/fundamental_service_port.py src/agents/fundamental/infrastructure/fundamental_service_client.py src/agents/fundamental/interface/fundamental_service_contracts.py tests/agents/fundamental/test_fundamental_service_client.py`: passed.
- `python3 scripts/architecture_guard.py`: passed with no boundary violations.
- `git diff --check origin/main...HEAD`: passed.

The focused service tests cover SEC source capture, ambiguous and mismatched identity evidence, the signed resolver route, authorization, rate limiting, source failures, and the typed OpenAPI contract. The Agent tests cover the signed client request and digest-bound response validation.

## Remaining verification

- No Docker project has been built from this branch. The healthy #325 containers use a different worktree and do not count as #336 health evidence.
- No live SEC identity resolution has run through the #336 service image.
- No resolved identity has yet been sent through the existing ingestion and snapshot-resolution HTTP routes.
- The full service suite skipped 25 checks. Their reasons are not yet classified.
- No PR or PR CI exists. Issue #336 and its dependent issue #325 remain open.

The next checkpoint is an isolated Docker service run on unique host ports. It must verify the resolver response against the existing SEC ingestion and snapshot contracts before this issue can move to acceptance review.
