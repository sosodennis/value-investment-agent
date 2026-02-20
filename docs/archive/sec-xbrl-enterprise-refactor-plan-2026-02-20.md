# SEC XBRL Enterprise Refactor Plan
Date: 2026-02-20
Owner: Fundamental Data (SEC XBRL)

## Goal
Replace first-hit extraction with an enterprise-grade resolution pipeline:
1. filing-level extension concept discovery + issuer-specific mapping
2. dimension/context-aware fallback (not consolidated-only)
3. deterministic candidate scoring + full resolution trace

This plan is intentionally breaking-change oriented. We do not keep compatibility shims for legacy extraction behavior.

## Non-Goals
1. No backward-compatibility guarantee for old field-selection order.
2. No temporary dual-pipeline runtime in production path.
3. No mixed contract where old and new provenance schema coexist long-term.

## Current Problems
1. `factory._extract_field` returns on first parseable hit, lacks global candidate ranking.
2. Dedup in extractor can collapse semantically different facts if concept/value same but context differs.
3. Mapping is industry-level only, weak for issuer-specific extension concepts.
4. Dimensional facts are supported but not treated as first-class fallback policy.

## Target Architecture
1. `fact_store`: load and normalize filing facts with context metadata.
2. `candidate_engine`: query facts using concept regex + statement/period/unit/dimension policy.
3. `resolver`: score candidates and output one selected fact + ranked alternatives.
4. `mapping layers`:
   - base taxonomy mapping
   - issuer-specific override mapping
5. `resolution_trace`: persisted diagnostic structure per resolved field.

## Breaking Changes
1. Field resolution is score-driven; selected concept may differ from old implementation.
2. Extraction diagnostics schema is replaced by structured `resolution_trace` fields.
3. Search dedup key changes to include period/unit/dimension/context identity.
4. Issuer overrides can supersede industry defaults by policy.

## Phases

### Phase 0: Design + Contract Freeze
1. Define resolver data contracts (`FactCandidate`, `ResolutionResult`, scoring factors).
2. Define issuer override contract (`issuer`, `field_key`, `query list`, priority).
3. Freeze resolution policy order.

### Phase 1: Extraction Core Refactor
1. Introduce candidate/resolver models.
2. Fix dedup identity to include context dimensions.
3. Replace first-hit logic with score-based selection in `factory._extract_field`.

### Phase 2: Issuer-Specific Override Layer
1. Add issuer override registry.
2. Load and apply overrides before generic fallback for targeted fields.
3. Add diagnostics showing whether base mapping or issuer override won.

### Phase 3: Dimension/Context Fallback Policy
1. Introduce explicit fallback chain:
   - strict consolidated
   - strict dimensional policy
   - relaxed context policy
2. Persist fallback stage in trace.

### Phase 4: Validation and Rollout
1. Golden tests for selected tickers across industries.
2. Field-level validation against SEC companyfacts/companyconcept.
3. Remove deprecated code paths.

## Test Strategy
1. Unit tests
   - resolver scoring and tie-break determinism
   - dedup identity correctness
   - issuer override precedence
2. Integration tests
   - representative tickers: AAPL, MSFT, JPM, O, PLD
   - assert selected concept and value for key fields
3. Regression tests
   - ensure no unresolved error regressions in core base fields

## Definition of Done
1. No first-hit extraction logic remains in production path.
2. All resolved fields include deterministic provenance/trace metadata.
3. Issuer overrides and dimensional fallback are both active.
4. Golden tests pass for cross-industry ticker set.

## Progress
- [x] Phase 0 completed
- [x] Phase 1 completed
- [x] Phase 2 completed
- [x] Phase 3 completed
- [x] Phase 4 completed

## Execution Log
### 2026-02-20
1. Created enterprise refactor plan document and locked breaking-change direction.
2. Phase 1 executed:
   - Added candidate ranking/selection module:
     - `finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/resolver.py`
   - Replaced first-hit extraction behavior in:
     - `finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/factory.py`
     - `_extract_field` now evaluates all parseable candidates and selects by deterministic scoring.
   - Updated extractor dedup identity to include period/unit/dimension/value context:
     - `finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/extractor.py`
3. Added Phase 1 regression tests:
   - `finance-agent-core/tests/test_sec_xbrl_resolver.py`
4. Validation results:
   - `ruff check` passed for touched sec_xbrl refactor files.
   - `pytest` passed on sec_xbrl suites:
     - `test_sec_xbrl_resolver.py`
     - `test_sec_xbrl_mapping_fallbacks.py`
     - `test_sec_xbrl_extension_industry_routing.py`
     - `test_sec_xbrl_total_debt_policy.py`
5. Phase 2 executed:
   - Added issuer-level resolution contract in mapping registry:
     - `resolve(field_key, industry, issuer)` with source tracking (`issuer_override` / `industry_override` / `base`)
     - `register_issuer_override(...)`
   - Updated extraction factories to use resolver path for all base/extension field lookups:
     - `BaseFinancialModelFactory.create(...)`
     - `FinancialReportFactory._create_industrial_extension(...)`
     - `FinancialReportFactory._create_financial_services_extension(...)`
     - `FinancialReportFactory._create_real_estate_extension(...)`
   - Added mapping diagnostics logs:
     - `fundamental_xbrl_mapping_resolved`
     - `fundamental_xbrl_mapping_missing`
6. Phase 2 regression tests:
   - Added resolver precedence tests (issuer > industry > base) in:
     - `finance-agent-core/tests/test_sec_xbrl_mapping_fallbacks.py`
   - Updated routing tests to assert industry + issuer propagation in:
     - `finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py`
7. Validation results (Phase 2):
   - `ruff check` passed for touched mapping/factory/tests files.
   - `pytest` passed:
     - `test_sec_xbrl_mapping_fallbacks.py`
     - `test_sec_xbrl_extension_industry_routing.py`
     - `test_sec_xbrl_resolver.py`
     - `test_sec_xbrl_total_debt_policy.py`
8. Phase 3 executed:
   - Implemented explicit fallback chain in field extraction:
     - `strict_primary`
     - `strict_dimensional`
     - `relaxed_context`
   - Added deterministic stage de-duplication for search configs to avoid repeated scans.
   - Added stage marker to hit diagnostics:
     - `resolution_stage` in `fundamental_xbrl_field_hit`
   - Expanded missing-field provenance text to include searched stages.
9. Phase 3 regression tests:
   - Added extraction fallback-chain tests in:
     - `finance-agent-core/tests/test_sec_xbrl_resolver.py`
10. Validation results (Phase 3):
   - `ruff check` passed for touched files.
   - `pytest` passed:
     - `test_sec_xbrl_mapping_fallbacks.py`
     - `test_sec_xbrl_extension_industry_routing.py`
     - `test_sec_xbrl_resolver.py`
     - `test_sec_xbrl_total_debt_policy.py`
11. Phase 4 (in progress) smoke validation:
   - Ran live extraction smoke tests for cross-industry tickers:
     - `AAPL`, `MSFT`, `JPM`, `O`, `PLD`
   - All tickers returned report objects without extraction exceptions.
   - Added field-level source confirmation via runtime diagnostics:
     - `resolution_stage` markers surfaced in `fundamental_xbrl_field_hit`
     - debt policy decomposition surfaced in `fundamental_total_debt_policy_applied`
12. Web/SEC cross-verification (companyconcept API):
   - Confirmed selected values for extracted fields against SEC XBRL API:
     - `AAPL us-gaap:Assets (2025-09-27) = 359,241,000,000`
     - `JPM us-gaap:LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities (2025-12-31) = 435,206,000,000`
     - `JPM us-gaap:RevenuesNetOfInterestExpense (2025-12-31) = 182,447,000,000`
     - `O us-gaap:Revenues (2024-12-31) = 5,271,142,000`
     - `PLD us-gaap:Revenues (2025-12-31) = 8,790,127,000`
13. Runtime debt-tag confirmation sample (O):
   - Total debt resolved as computed:
     - `Debt (Excluding Finance Leases) + Finance Lease Liabilities`
   - Core XBRL components:
     - `us-gaap:NotesPayable`
     - `us-gaap:LoansPayable`
     - `us-gaap:CommercialPaper`
     - `us-gaap:FinanceLeaseLiability`
14. Phase 4 rollout finalized with reusable live golden tests:
   - Added new integration suite:
     - `finance-agent-core/tests/test_sec_xbrl_live_golden.py`
   - Coverage set includes cross-industry tickers and SEC companyconcept cross-check:
     - `AAPL`, `MSFT`, `JPM`, `O`, `PLD`
   - Added runtime gate for external/live validation:
     - run only when `SEC_XBRL_LIVE_TESTS=1`
15. Test runner integration updates:
   - Registered pytest marker in:
     - `finance-agent-core/pyproject.toml`
     - marker: `integration`
16. Validation results (Phase 4 completion):
   - Default test mode (no live env):
     - `test_sec_xbrl_live_golden.py` skipped deterministically
   - Live sanity run:
     - `SEC_XBRL_LIVE_TESTS=1 ... -k aapl_assets_2025` passed
   - Combined sec_xbrl suite:
     - `30 passed, 5 skipped`
