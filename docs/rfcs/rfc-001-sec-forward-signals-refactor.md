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

## 5. Module Plan

Add modules under `sec_xbrl`:

1. `signal_schema.py`
   Pydantic models for forward signal payload and evidence.
2. `filing_fetcher.py`
   SEC fetch + rate limit + retry policy.
3. `section_extractor.py`
   Section extraction with ordered strategies.
4. `sentence_pipeline.py`
   Text normalization + two-stage segmentation (char pre-chunk + spaCy sentencizer).
5. `hybrid_retriever.py`
   BM25 + dense embeddings + RRF fusion.
6. `signal_builder.py`
   Deterministic conversion from evidence into signal payload.
7. `model_registry.py`
   Centralized singleton loaders for NLP models.

`forward_signals_text.py` becomes façade/orchestrator for these modules.

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

### Benchmark Command (PR-5)

Run fixed-eval benchmark locally:

```bash
uv run --project finance-agent-core python finance-agent-core/scripts/benchmark_sec_forward_signals.py --iterations 8
```

## 11. Acceptance Criteria

1. All relevant tests pass.
2. On fixed evaluation set:
   - Precision improvement for `growth_outlook`/`margin_outlook`.
   - Zero emitted signals without valid evidence.
3. 429/transient failures recover without crashing the job.
4. Every emitted signal traces to accession and filing-level source link.
5. Container cold start does not download models.
6. Sentence-level evidence stays intact after chunking (no broken numeric guidance token spans).

## 12. Risks and Mitigations

1. FinBERT label mapping mistakes
   - Read `id2label` from model config and lock with tests.
2. CPU latency regression
   - Batch inference and cap candidate size.
3. Third-party API drift
   - Isolate third-party access in adapter modules and test with stubs.
