# RFC-001: SEC Forward Signals Refactor (Single Path, No Feature Flag)

Status: Draft
Author: Architecture Proposal (Codex)
Date: 2026-02-25

## Scope

Target modules:

- `finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/forward_signals_text.py`
- `finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/forward_signals.py`
- `finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/utils.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/assumptions.py`

## 1. Context and Current Gaps

The current implementation works and tests pass, but it still has enterprise-level gaps:

1. No explicit SEC rate limiting/backoff strategy.
2. Forward signal payloads are weakly typed (`dict[str, object]`) and can be silently dropped downstream.
3. Evidence URLs are search-level, not filing-level deep links (weaker auditability).
4. Retrieval precision can improve for long filing text.

This RFC follows a strict constraint:

1. No feature flag.
2. No dual pipeline.
3. Migrate directly to one path.

## 2. Decision Summary

Adopt a single new pipeline while preserving output contract compatibility:

1. Keep public function `extract_forward_signals_from_sec_text(...)`.
2. Replace internal logic with two-stage segmentation (`RecursiveCharacterTextSplitter` pre-chunk + spaCy sentence segmentation), then FinBERT-FLS filtering + hybrid retrieval + deterministic scoring.
3. Keep downstream-compatible forward signal schema keys.
4. Internally enforce typed validation (Pydantic v2), output via `model_dump()`.
5. Keep v1 effective metrics as `growth_outlook` and `margin_outlook`.

## 3. Goals / Non-Goals

Goals:

1. Improve precision and evidence quality for forward-looking statements.
2. Improve traceability (accession, filing date, filing-level URL).
3. Improve runtime resilience (rate limiting, retry with jitter, classified errors).
4. Keep valuation policy behavior stable.

Non-goals:

1. No LLM extraction in this refactor.
2. No external vector database in phase 1 (in-memory only).
3. No legacy regex-only fallback path retained as a parallel version.

## 4. Target Architecture

```mermaid
flowchart LR
    A["EDGAR Filings"] --> B["Section Extractor (10-K/10-Q/8-K)"]
    B --> C["Char Pre-Chunk (RecursiveCharacterTextSplitter)"]
    C --> D["spaCy Sentencizer"]
    D --> E["FinBERT-FLS Filter"]
    E --> F["Hybrid Retriever (BM25 + Dense + RRF)"]
    F --> G["Deterministic Signal Builder"]
    G --> H["Typed Signal + Typed Evidence"]
    H --> I["Valuation Policy"]
```

## 5. Module Plan (Clean Architecture Aligned)

Layering decision:

1. `fundamental/domain` holds business policy and scoring rules.
2. `fundamental/application` orchestrates use cases.
3. `fundamental/data/clients/sec_xbrl` is a data adapter package (provider implementation).

Inside `sec_xbrl`, split by adapter responsibility without adding nested `data_layer/`:

1. `provider.py`
   - Thin adapter façade with stable public API.
   - No heavy matching/scoring logic.
2. `forward_signals_text.py`
   - SEC text extraction pipeline orchestration (temporary, to be decomposed).
3. `forward_signals.py`
   - Deterministic XBRL trend-based signal producer.
4. Adapter modules:
   - `filing_fetcher.py`, `filing_section_selector.py`, `sentence_pipeline.py`, `fls_filter.py`, `hybrid_retriever.py`.
5. `matchers/`
   - `regex_signal_extractor.py`, `lemma_signal_matcher.py`, `dependency_signal_matcher.py`.
6. `rules/`
   - `schema.py`, `loader.py`, `patterns/`, `lexicons/`.

`__init__.py` exports from `provider.py` to preserve compatibility.

## 6. Contract Strategy

Public signature remains:

- `extract_forward_signals_from_sec_text(...) -> list[dict[str, object]]`

Internal rules:

1. Build and validate typed signal models.
2. Serialize with `model_dump()`.
3. Keep required fields:
   - `signal_id`
   - `source_type`
   - `metric`
   - `direction`
   - `value`
   - `unit`
   - `confidence`
   - `as_of`
   - `evidence`
4. Evidence must include (when available):
   - `accession_number`
   - `filing_date`
   - `doc_type`
   - filing-level `source_url`

## 7. Core Rules

1. `source_type` must stay in downstream supported set.
2. Confidence clamped to `[0.0, 1.0]`.
3. Unit normalized to `basis_points`.
4. No evidence means no emitted signal.
5. Staleness penalty remains explicit and testable.

## 8. Dependencies and Runtime

Planned dependencies:

1. `transformers`
2. `sentence-transformers`
3. `rank-bm25`
4. `spacy` (chosen)

Segmentation defaults:

1. Pre-chunk with `RecursiveCharacterTextSplitter` using:
   - `chunk_size=3000`
   - `chunk_overlap=250`
   - separators ordered as paragraph/newline/sentence fallback
2. Sentence segmentation with `spacy.blank("en")` + `sentencizer`.
3. Run FinBERT-FLS only on sentence units, not raw char chunks.

Container setup:

1. Set `HF_HOME` as the canonical model cache root.
2. Pre-download model assets at build time.
3. Initialize spaCy runtime (sentencizer path) in image build validation step.
4. Avoid runtime model download during startup.

## 9. Compatibility and Breaking Changes

Compatibility:

1. Upstream/downstream integration remains contract-compatible at payload key level.
2. Existing valuation policy path remains unchanged.

Breaking behaviors:

1. Legacy regex-only execution path is removed.
2. Missing model artifacts become configuration/deployment errors (fail fast).

## 10. Implementation Steps

1. PR-1: schema and façade refactor (Done 2026-02-25)
   - Add typed schemas and serialization boundaries.
2. PR-2: fetch hardening (Done 2026-02-25)
   - Add rate limiting, retry, and jitter.
3. PR-3: retrieval pipeline (Done 2026-02-25)
   - Add two-stage segmentation pipeline, FinBERT filter, hybrid retriever, deterministic builder.
4. PR-4: observability and provenance (Done 2026-02-25)
   - Improve deep-link evidence and structured logs.
5. PR-5: tests and benchmark (Done 2026-02-25)
   - Update fixtures and add quality/perf checks.

### Wrapper Sunset Plan

Current temporary wrappers:

1. `sec_xbrl/provider.py` as stable adapter entrypoint.

Removed in refactor phases:

1. Legacy import shims removed:
   - `regex_signal_extractor.py`
   - `lemma_signal_matcher.py`
   - `dependency_signal_matcher.py`
   - `signal_pattern_catalog.py`
2. Internal compatibility wrappers removed from `forward_signals_text.py`:
   - `_fetch_recent_filing_text_records(...)`
   - `_group_records_for_signals(...)`

Removal policy:

1. Keep wrappers through P0/P1 while structure stabilizes and tests are green.
2. Start removal in P2 only after:
   - zero external imports of legacy shim paths (codebase + scripts),
   - CI eval gate passes on fixed benchmark set,
   - one full release cycle in dev/staging without wrapper-only regressions.
3. Remove in this order:
   - internal function wrappers in `forward_signals_text.py` (Done),
   - legacy module import shims (Done),
   - final `provider.py` only if upstream `application` port has fully replaced direct client imports.

Current status:

1. `fundamental/application/factory.py` now injects `IFundamentalFinancialPayloadProvider`.
2. `application` imports `sec_xbrl.provider.fetch_financial_payload` only; direct `sec_xbrl.utils` import is removed.
3. Runtime signal catalog now loads from `rules/*.yml` via `rules/loader.py`; legacy hardcoded phrase catalog body has been removed.

Enforcement guards:

1. Legacy shim import guard test:
   - `finance-agent-core/tests/test_sec_xbrl_legacy_import_guard.py`
2. Provider entrypoint import guard test (outside `sec_xbrl` package):
   - `finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py`

## 11. Sector Lexicon Skeleton (Data-Driven Rules)

Purpose:

1. Move wording variation out of Python code and into versioned configuration.
2. Support ticker style differences via global defaults + sector overlays.
3. Keep matcher code stable while enabling fast lexicon updates.

Proposed skeleton:

```text
finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/rules/
  schema.py
  loader.py
  patterns/
    global.yml
  lexicons/
    global.yml
    sectors/
      technology.yml
      consumer_discretionary.yml
      financials.yml
```

Example `lexicons/global.yml`:

```yaml
version: 1
forward_cues:
  - expect
  - anticipate
  - outlook
  - guidance
signals:
  growth_outlook:
    aliases:
      - revenue growth
      - top line growth
      - demand growth
  margin_outlook:
    aliases:
      - gross margin
      - operating margin
      - margin pressure
```

Example `lexicons/sectors/technology.yml`:

```yaml
version: 1
extends: global
signals:
  margin_outlook:
    aliases:
      - cloud mix shift
      - datacenter pricing pressure
      - ad load headwind
```

Loader behavior:

1. Load `global.yml` first.
2. Apply `sectors/<sector>.yml` as additive override.
3. Validate with `schema.py`; fail fast on invalid files.
4. Emit deterministic merged config for matchers.

## 12. Rules Placement Decision (Cohesion)

Decision:

1. Keep `rules/` physically inside `sec_xbrl` adapter package.
2. Treat rules as internal assets of the SEC text extraction pipeline.

Rationale:

1. Highest cohesion: only this SEC adapter pipeline consumes these files.
2. Clear ownership: SEC forward-signal team owns matcher logic + rule assets together.
3. Lower accidental coupling: domain/application layers depend on interfaces and typed outputs, not rule file formats.

Boundary guardrails:

1. `domain/` and upper layers must not read YAML directly.
2. Only `rules/loader.py` exposes typed config objects to matcher modules.
3. If another client needs shared rules later, extract to a separate `shared_rules` package intentionally (not by ad-hoc imports).

### Benchmark Command (PR-5)

Run fixed-eval benchmark locally:

```bash
uv run --project finance-agent-core python finance-agent-core/scripts/benchmark_sec_forward_signals.py --iterations 8
```

## 13. Acceptance Criteria

1. All relevant tests pass.
2. On fixed evaluation set:
   - Precision improvement for `growth_outlook`/`margin_outlook`.
   - Zero emitted signals without valid evidence.
3. 429/transient failures recover without crashing the job.
4. Every emitted signal traces to accession and filing-level source link.
5. Container cold start does not download models.
6. Sentence-level evidence stays intact after chunking (no broken numeric guidance token spans).

## 14. Risks and Mitigations

1. FinBERT label mapping mistakes
   - Read `id2label` from model config and lock with tests.
2. CPU latency regression
   - Batch inference and cap candidate size.
3. Third-party API drift
   - Isolate third-party access in adapter modules and test with stubs.
