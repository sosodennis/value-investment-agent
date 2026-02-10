# XBRL Data Quality & Governance TODO (Enterprise Checklist)

> Goal: Harden SEC XBRL extraction with enterprise-grade validation, provenance, and auditability.
> Approach: Implement in incremental phases, with tests and measurable coverage at each step.

## Phase 0 — Baseline Instrumentation
- [x] Add structured logging for XBRL extraction (field, tag, period, statement).
- [ ] Add extraction metrics summary per report (hits, misses, skipped by reason).
- [ ] Emit `missing_inputs` with reasons (not just names).

## Phase 1 — Context & Statement Hygiene
- [x] Filter by **statement type** (BS/IS/CF) for each target field.
- [x] Enforce **period type** rules:
  - Balance sheet: `instant`
  - Income statement / cash flow: `duration`
- [x] Enforce **period end** alignment to the filing’s `DocumentPeriodEndDate`.
- [ ] Track and reject **context mismatch** (wrong fiscal year/period).

## Phase 2 — Unit & Scale Normalization
- [x] Validate units (e.g., USD, shares, pure) with unit whitelists.
- [x] Normalize `scale` in numeric parsing.
- [ ] Normalize `decimals` consistently.
- [ ] Reject values with incompatible units (explicit reasons).
- [ ] Support per-field expected units (metadata registry).

## Phase 3 — Dimensional Hygiene (Consolidated vs Segments)
- [x] Consolidated-only mode by default.
- [x] Detect & exclude dimensional facts (segment/axis contamination).
- [x] Optional: allow segment-specific extraction when explicitly requested.

## Phase 4 — Tag Mapping & Priority Tables
- [x] Build a **mapping registry** per field with ordered tag priority.
- [x] Maintain **industry-specific overrides** (e.g., banks, REITs).
- [x] Log rejected candidate tags with reasons (unit mismatch, wrong period, etc.).

## Phase 5 — Internal Consistency Checks
- [ ] Validate `Assets ≈ Liabilities + Equity`.
- [ ] Validate `Revenue >= 0`, `Cash >= 0`, `Shares > 0` (unless disclosure says otherwise).
- [ ] Validate `OCF` directionality vs `Net Income` (basic sanity).
- [ ] Flag extreme changes year-over-year (outlier detection).

## Phase 6 — Coverage & Confidence Scoring
- [ ] Compute coverage % per model (required fields vs found).
- [ ] Compute confidence score per field (tag quality, statement match, context match).
- [ ] Enforce minimum confidence thresholds per model.

## Phase 7 — Provenance & Auditability
- [ ] Store extraction provenance for **each candidate** (not just chosen one).
- [ ] Persist provenance artifacts alongside calculation outputs.
- [ ] Provide full audit trail in the UI (field → tag → period → unit → statement).

## Phase 8 — Regression & Golden Tests
- [ ] Build golden ticker set by industry (Tech, Bank, REIT, Industrials).
- [ ] Snapshot expected values + provenance.
- [ ] Add regression tests for tag mapping changes.

## Phase 9 — Production Governance
- [ ] Versioned tag mapping tables with changelog.
- [ ] Data quality SLA metrics (daily coverage %, failure counts).
- [ ] Alerting on extraction anomalies (missing critical fields, sudden value jumps).

---

## Implementation Notes (Suggested Order)
1. Phase 1 (Context/Statement hygiene)
2. Phase 2 (Unit/Scale normalization)
3. Phase 3 (Dimensional hygiene)
4. Phase 4 (Tag mapping registry)
5. Phase 5 (Consistency checks)
6. Phase 6 (Coverage/Confidence scoring)
7. Phase 7 (Auditability expansion)
8. Phase 8 (Tests)
9. Phase 9 (Governance)

---

## Current Status
- Derived field calculations: ✅ (Working capital, NOPAT, ROIC, etc.)
- Missing inputs surfaced: ✅
- Phase 1 (context/statement/period filters): ✅
- Phase 2 (unit/scale normalization): 🟡 (scale done, decimals pending)
- Enterprise data quality gate: 🚧 (in progress)
