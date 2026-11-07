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

- The isolated Docker project `value-investment-agent-issue-336-issuer-identity` uses PostgreSQL host port `18694` and service host port `18693`.
- The service image built from code checkpoint `9253f820656b3fa976ce2c14e08eaf88d5fba3b9` has digest `sha256:aec7b3e0c6f29124815129019c2d3202f0d57dc4fb84eaf897823f459797c5b3`.
- PostgreSQL became healthy, but the Fundamental service exited with code 1 because the configured EDGAR plugin hash did not match the mounted directory. The service health check did not pass. `/readyz` returned connection error 7.
- The healthy #325 containers use a different worktree and do not count as #336 health evidence.
- No live SEC identity resolution has run through the #336 service image.
- No resolved identity has yet been sent through the existing ingestion and snapshot-resolution HTTP routes.
- The full service suite skipped 25 checks. Their reasons are not yet classified.
- No PR or PR CI exists. Issue #336 and its dependent issue #325 remain open.

The next checkpoint is to identify the matching pinned EDGAR plugin artifact, rebuild the isolated service, and verify its resolver response against the existing SEC ingestion and snapshot contracts.
