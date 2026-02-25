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

## 5. Module Plan (Clean Architecture Naming)

Keep `sec_xbrl` as the data-layer client package and split by responsibility:

1. `application/` (use-case orchestration inside this client)
   - `forward_signal_pipeline.py`: pipeline orchestration only.
2. `domain/` (business rules local to this bounded context)
   - `signal_models.py`: typed signal/evidence models.
   - `scoring.py`: deterministic confidence/value scoring.
3. `data_layer/` (adapters and external dependencies)
   - `filing_fetcher.py`: SEC fetch + rate limit + retry policy.
   - `filing_section_selector.py`: section extraction with ordered strategies.
   - `sentence_pipeline.py`: text normalization + segmentation.
   - `fls_filter.py`: forward-looking sentence classifier adapter.
   - `hybrid_retriever.py`: BM25 + dense retrieval + fusion.
   - `matchers/`: regex/lemma/dependency matcher implementations.
4. `rules/` (data configuration consumed by data-layer matchers)
   - `schema.py`: Pydantic schema for rule and lexicon files.
   - `loader.py`: validation + merge (global + sector overlays).
   - `patterns/`: rule files.
   - `lexicons/`: global and sector lexicon files.

`forward_signals_text.py` stays as a compatibility façade and delegates to `application/forward_signal_pipeline.py`.

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

1. Keep `rules/` physically inside the `sec_xbrl` data-layer package.
2. Treat rules as internal assets of the SEC text extraction pipeline.

Rationale:

1. Highest cohesion: only this data-layer pipeline consumes these files.
2. Clear ownership: SEC forward-signal team owns matcher logic + rule assets together.
3. Lower accidental coupling: domain/application layers depend on interfaces and typed outputs, not rule file formats.

Boundary guardrails:

1. `domain/` and upper layers must not read YAML directly.
2. Only `rules/loader.py` exposes typed config objects to data-layer matchers.
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
