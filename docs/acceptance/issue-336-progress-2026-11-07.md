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
- The attempted plugin hashes came from the earlier #312 progress record. Commit `27ede857` changed `arelle_parser._directory_hash` to ignore `__pycache__`, `.pyc`, and `.pyo` files, so those recorded hashes no longer match the current stable hash function.
- Recomputing the mounted resources with the current helper produced EDGAR hash `054a21fa824797787acc2c6e98af4bb040c51bbee41b613cee1793db8fd144af` and Xule hash `63123d67048019e3c49a0efde0e0aa8ec3eba0fc971da56ebd96dea8e40cd713`. The taxonomy cache hash remains `23201023716b144aefca4864bc6e4ee055aad864f2e13f3ff1ef652354a1d42c`.
- The healthy #325 containers use a different worktree and do not count as #336 health evidence.
- No live SEC identity resolution has run through the #336 service image.
- No resolved identity has yet been sent through the existing ingestion and snapshot-resolution HTTP routes.
- The full service suite skipped 25 checks. Their reasons are not yet classified.
- No PR or PR CI exists. Issue #336 and its dependent issue #325 remain open.

## Live service checkpoint

- The isolated Compose project `value-investment-agent-issue-336-issuer-identity`
  reported healthy PostgreSQL and Fundamental service containers. `GET
  http://127.0.0.1:18693/readyz` exited 0 with HTTP 200 and
  `{"status":"ready","contract_version":"internal.v1"}`. The running
  Fundamental image ID is
  `sha256:aec7b3e0c6f29124815129019c2d3202f0d57dc4fb84eaf897823f459797c5b3`.
- A signed `internal.v1` request using Bearer `integration-token`, organization
  `org-sec-ingestion-test`, and correlation ID
  `issue-336-live-identity-aapl` reached `POST
  http://127.0.0.1:18693/v1/identity/resolve` and exited 0 with HTTP 200. The
  service resolved `AAPL` to issuer `0000320193`, `Apple Inc.`, US GAAP, USD,
  and returned `mapping_version=sec-issuer-identity-v1`. The three captured SEC
  source records had byte counts `796507`, `164533`, and `3859564`, content
  hashes `76b4b2abb9f7dd0e9cff38e2f20336952bb41806057b2dd1033e244f3e1faec2`,
  `73e35ef6e705188999d1cd868727a0ac7524cd470cca647f60033f6318eff3c4`, and
  `f085735b4d08fb116ade18d24247ffabe11df8eb52eae6556b165831f15ef1ad`, and
  resolution digest
  `bcbcebee7916effd630fb47aef0929bc6c899c826f1927b643f07da27b53a00f`.
- The same resolved identity was submitted to `POST
  http://127.0.0.1:18693/v1/data/ingestions` with AAPL accession
  `0000320193-24-000123`, required field `revenue`, and the pinned Arelle
  `2.47.4` / `sec-efm-us-dqc-v31.0.3` profile. The service returned HTTP 422
  `FACT_MAPPING_UNRESOLVED` before acquisition, so no snapshot was published.
- The disposable verification database was then seeded through the existing
  service-owned `PostgresMetadataStore.publish_mapping` API with the approved
  `sec-revenue-v1` mapping (`us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`,
  mapping version `sec-us-gaap-v1`, mapping digest
  `2c5ac7dca0856e509c6f0baaf5c15040094bba2988d9a81daf41af3d17e48d44`). The
  same signed ingestion request reached the parser and returned HTTP 422
  `PARSER_VALIDATION_BLOCKED`; PostgreSQL contains zero ingestion acquisitions,
  zero snapshots, and zero canonical facts, while the audit table records the
  `PARSER_VALIDATION_BLOCKED` outcome. This is the expected fail-closed result
  for the known AAPL filing and proves the resolved identity crosses the
  existing ingestion boundary without a second SEC path.
- A signed `POST /v1/data/snapshots/resolve` request carrying the same AAPL
  identity returned HTTP 422 `DATA_RELEASE_PROFILE_REQUIRED` without a release
  profile, and HTTP 503 `DATA_RELEASE_NOT_ACTIVE` when pinned to
  `sec-public-pit-v1`; neither path performed a local fallback or published
  data. A successful snapshot lookup therefore remains unavailable in this
  fresh verification database until a data release is activated by the owning
  #321 workflow.

The next checkpoint is to rebuild the isolated service with the recomputed resource hashes and verify its resolver response against the existing SEC ingestion and snapshot contracts.
