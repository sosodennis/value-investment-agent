# Issue 119 acceptance report

## Result

- Base SHA: `84c563ceecb1500c6bb2a5800e7b8c0aca89fb5e` (`origin/main`)
- Branch: `codex/issue-118-119-contract`
- Result SHA: `a7fe8b6d50a1a6c9c806798072ef4225bb5f4d7c` (implementation and fake-service readiness coverage)
- Verdict: **PASS** for the shared contract scope in Issue 119
- PR: https://github.com/sosodennis/value-investment-agent/pull/127

## Changed files

- `finance-agent-core/src/shared/internal_services/contracts.py` defines `internal.v1`, authenticated principal, correlation ID, absolute UTC deadline, redacted error, and readiness wire models.
- `finance-agent-core/src/shared/internal_services/auth.py` authenticates the backend service token with constant-time comparison before parsing or trusting the principal context.
- `finance-agent-core/src/shared/internal_services/README.md` documents request, response, error, readiness, authentication, redaction, and fake-service conventions.
- `finance-agent-core/tests/fakes/internal_capability_service.py` provides an in-process FastAPI fake that imports only shared contracts and FastAPI, with configurable ready and not-ready states.
- `finance-agent-core/tests/test_internal_service_contracts.py` covers malformed contexts, missing or invalid credentials, required versions, UTC deadline parsing, redaction, errors, and readiness.
- `finance-agent-core/tests/test_internal_service_fake.py` covers authenticated correlation, fail-closed authentication before principal use, and both ready and not-ready HTTP readiness responses.
- `.audit/issue-119-architecture.md` records ownership, alternatives, and the synthesis decision.
- `.audit/issue-119.tsv` records the decision trail.

## Baseline evidence

- `finance-agent-core/src/auth/interface/dependencies.py:31-40` authenticates the browser session and derives the API principal.
- `finance-agent-core/src/auth/interface/contracts.py:10-21` maps the authenticated user record to `Principal.user_id` and `subject`.
- `finance-agent-core/src/llm_provider/domain/contracts.py:55-66,113-127` has an LLM-specific user principal and request ID/timeout fields.
- `finance-agent-core/src/model_inference/domain/contracts.py:54-59` carries inference operation, request ID, and a relative millisecond deadline.
- `finance-agent-core/src/model_inference/infrastructure/http_adapter.py:80-107` sends an optional bearer token and `X-Request-ID` header.
- `finance-agent-core/src/shared/kernel/README.md:5-24` assigns stable, non-provider primitives to shared code and excludes clients and API DTO assembly.
- `docker-compose.yml:1-37` configures inference readiness separately from service request contracts.
- `finance-agent-core/src/agents/news/infrastructure/search/ddg_news_search_provider.py:7-28` and `finance-agent-core/src/agents/intent/application/ports.py:11-32` show Search currently lives behind agent-owned providers and ports.

## Verification

All commands ran against the implementation commit tree. The report and audit trail were updated afterward.

| Command | Result |
| --- | --- |
| `uv run pytest tests/test_internal_service_contracts.py tests/test_internal_service_fake.py tests/test_model_inference.py tests/test_llm_provider_contract.py -q` | **PASS**, 47 passed, 4 existing dependency deprecation warnings |
| `uv run ruff check src/shared/internal_services tests/test_internal_service_contracts.py tests/test_internal_service_fake.py tests/fakes/internal_capability_service.py` | **PASS**, all checks passed |
| `uv run ruff format --check src/shared/internal_services tests/test_internal_service_contracts.py tests/test_internal_service_fake.py tests/fakes/internal_capability_service.py` | **PASS**, 6 files already formatted |
| `python3 scripts/architecture_guard.py` | **PASS**, no boundary violations |
| `git diff --check` | **PASS** |

The implementation result SHA is the code commit above. The acceptance report and PR metadata are committed in later documentation commits on the PR branch.

The architect arena dispatch was attempted as required by the pstack architecture workflow. The host rejected the dispatch because the agent thread limit was reached. The design record names that limitation and compares the nested context envelope against a header-only alternative and per-service shared DTOs.

The agent thread limit also prevented an independent cross-model review of the decision trail. The implementation was reviewed locally, the staged diff passed repository hooks, and the automated checks above passed.

## Integration instructions for #120 and #121

1. Derive `InternalPrincipal.subject_id` from the authenticated backend session at the product API boundary. Do not accept a browser-selected user ID.
2. Send `Authorization: Bearer <configured backend-to-service token>` separately from the JSON body. Configure and rotate the token in deployment secrets. Do not forward browser cookies, CSRF tokens, browser bearer tokens, raw provider keys, prompts, or article content as identity metadata.
3. Send the required `context` object with `principal`, `correlation_id`, `contract_version: "internal.v1"`, and an RFC 3339 `deadline_at` with an explicit UTC offset. Keep LLM and inference operation schemas in their own services.
4. At each service boundary, call `authenticate_internal_request` or reproduce its ordering exactly: authenticate the backend caller first, then parse the context, then validate the service-owned input. Map missing, invalid, or unconfigured service credentials to 401 and malformed context to 400.
5. Echo the same `correlation_id` and `contract_version` in successful responses and the shared error envelope. Reject mismatched correlation IDs or unsupported versions in clients. Keep error codes and HTTP mappings service-owned, bounded, and redacted.
6. Expose unauthenticated private-network `GET /readyz`. Return HTTP 200 with `{"status":"ready","contract_version":"internal.v1"}` only when the service can accept its documented operations. Return HTTP 503 with `status: "not_ready"` until then. Keep readiness conditions service-owned.
7. Use `tests/fakes/internal_capability_service.py` as the contract-test pattern. The fake must remain independent of backend implementation modules; add service-specific fake payloads and tests in each service repository or service package.
8. Use the absolute deadline as a decreasing request budget. Compute local transport timeout from remaining time and do not reset the budget at each hop.

For #120, map `context.principal.subject_id` to the service's existing owner key at the authenticated service boundary. Keep key ownership checks and all LLM/provider request and response schemas inside the LLM service. Echo the shared correlation/version fields around each service-owned response and error.

For #121, keep `news.sentiment` and `sec.fls` as service-owned operations. Replace the relative `deadline_ms` as the wire source with the shared absolute `deadline_at`; at the service boundary, calculate remaining monotonic time once and cap it by the existing operation policy. Retain the service-specific model revision and result schemas. Return shared correlation/version metadata and expose readiness only after required model loading and warmup complete.

## Remaining gaps

- This issue does not add HTTP middleware to LLM, inference, or Search. #120 and #121 must wire these primitives into their service boundaries.
- The token convention uses a configured shared secret. Mutual TLS, workload identity, token rotation overlap, and deployment network policy remain deployment concerns for the service issues.
- Readiness currently has a shared response shape only. Each service must implement its own dependency and model/provider readiness checks.
- The repository's existing Compose file has service-specific healthchecks. #120 and #121 should add or update service wiring without introducing fixed `container_name`, ports, or shared mutable volumes.
- Existing full-suite tests were not run because this change has no provider runtime or agent workflow changes. Focused regression coverage and the architecture guard passed.
- The agent thread limit prevented parallel architecture candidates, a cross-model trail review, and the pstack comment review. The architecture sketch records the candidate comparison and this limitation.
