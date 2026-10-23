# Issue 119 acceptance report

## Result

- Base SHA: `84c563ceecb1500c6bb2a5800e7b8c0aca89fb5e` (`origin/main`)
- Branch: `codex/issue-118-119-contract`
- Result SHA: `87020fc902b263eeb6d8120622205392a7152c4a` for implementation; the final report commit is added below
- Verdict: **PASS** for the shared contract scope in Issue 119
- PR: to be filled after push

## Changed files

- `finance-agent-core/src/shared/internal_services/contracts.py` defines `internal.v1`, authenticated principal, correlation ID, absolute UTC deadline, redacted error, and readiness wire models.
- `finance-agent-core/src/shared/internal_services/auth.py` authenticates the backend service token with constant-time comparison before parsing or trusting the principal context.
- `finance-agent-core/src/shared/internal_services/README.md` documents request, response, error, readiness, authentication, redaction, and fake-service conventions.
- `finance-agent-core/tests/fakes/internal_capability_service.py` provides an in-process FastAPI fake that imports only shared contracts and FastAPI.
- `finance-agent-core/tests/test_internal_service_contracts.py` covers malformed contexts, missing or invalid credentials, required versions, UTC deadline parsing, redaction, errors, and readiness.
- `finance-agent-core/tests/test_internal_service_fake.py` covers authenticated correlation, fail-closed authentication before principal use, and redacted readiness.
- `.audit/issue-119-architecture.md` records ownership, alternatives, and the synthesis decision.
- `.audit/issue-119.tsv` records the decision trail.

## Verification

All commands ran from the final worktree state.

| Command | Result |
| --- | --- |
| `uv run pytest tests/test_internal_service_contracts.py tests/test_internal_service_fake.py tests/test_model_inference.py tests/test_llm_provider_contract.py -q` | **PASS**, 46 passed, 4 existing dependency deprecation warnings |
| `uv run ruff check src/shared/internal_services tests/test_internal_service_contracts.py tests/test_internal_service_fake.py tests/fakes/internal_capability_service.py` | **PASS**, all checks passed |
| `uv run ruff format --check src/shared/internal_services tests/test_internal_service_contracts.py tests/test_internal_service_fake.py tests/fakes/internal_capability_service.py` | **PASS**, 6 files already formatted |
| `python3 scripts/architecture_guard.py` | **PASS**, no boundary violations |
| `git diff --check` | **PASS** |

The architect arena dispatch was attempted as required by the pstack architecture workflow. The host rejected the dispatch because the agent thread limit was reached. The design record names that limitation and compares the nested context envelope against a header-only alternative and per-service shared DTOs.

## Integration instructions for #120 and #121

1. Derive `InternalPrincipal.subject_id` from the authenticated backend session at the product API boundary. Do not accept a browser-selected user ID.
2. Send `Authorization: Bearer <configured backend-to-service token>` separately from the JSON body. Configure and rotate the token in deployment secrets. Do not forward browser cookies, CSRF tokens, browser bearer tokens, raw provider keys, prompts, or article content as identity metadata.
3. Send the required `context` object with `principal`, `correlation_id`, `contract_version: "internal.v1"`, and an RFC 3339 `deadline_at` with an explicit UTC offset. Keep LLM and inference operation schemas in their own services.
4. At each service boundary, call `authenticate_internal_request` or reproduce its ordering exactly: authenticate the backend caller first, then parse the context, then validate the service-owned input. Map missing, invalid, or unconfigured service credentials to 401 and malformed context to 400.
5. Echo the same `correlation_id` and `contract_version` in successful responses and the shared error envelope. Reject mismatched correlation IDs or unsupported versions in clients. Keep error codes and HTTP mappings service-owned, bounded, and redacted.
6. Expose unauthenticated private-network `GET /readyz`. Return HTTP 200 with `{"status":"ready","contract_version":"internal.v1"}` only when the service can accept its documented operations. Return HTTP 503 with `status: "not_ready"` until then. Keep readiness conditions service-owned.
7. Use `tests/fakes/internal_capability_service.py` as the contract-test pattern. The fake must remain independent of backend implementation modules; add service-specific fake payloads and tests in each service repository or service package.
8. Use the absolute deadline as a decreasing request budget. Compute local transport timeout from remaining time and do not reset the budget at each hop.

## Remaining gaps

- This issue does not add HTTP middleware to LLM, inference, or Search. #120 and #121 must wire these primitives into their service boundaries.
- The token convention uses a configured shared secret. Mutual TLS, workload identity, token rotation overlap, and deployment network policy remain deployment concerns for the service issues.
- Readiness currently has a shared response shape only. Each service must implement its own dependency and model/provider readiness checks.
- The repository's existing Compose file has service-specific healthchecks. #120 and #121 should add or update service wiring without introducing fixed `container_name`, ports, or shared mutable volumes.
- Existing full-suite tests were not run because this change has no provider runtime or agent workflow changes. Focused regression coverage and the architecture guard passed.
