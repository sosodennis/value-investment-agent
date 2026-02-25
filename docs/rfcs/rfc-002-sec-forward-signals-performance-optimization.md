# RFC-002: SEC Forward Signals Text Pipeline Performance Optimization

- Status: In Progress
- Author: Codex
- Date: 2026-02-25
- Scope: `finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl`
- Constraint: No feature flag, single implementation path

## 1. Background

`forward_signals_text` is currently the slowest part of fundamental analysis in some runs.

Recent log verification:

- Baseline (`docs/logs/fa.log`, run `d3150d31-c938-4db0-a1d1-81c43f40207c`)
  - `xbrl_to_text`: 182.097s
  - `fls_to_dense`: 38.950s
  - `dense_to_text`: 127.058s
- After corpus-embedding cache (`docs/logs/fa2.log`, run `6ee96c33-1aca-4eeb-86fa-53eab1338bf7`)
  - `xbrl_to_text`: 163.741s
  - `fls_to_dense`: 36.635s
  - `dense_to_text`: 110.816s

Result:

- `dense_to_text` improved by 16.242s (12.8%)
- `xbrl_to_text` improved by 18.356s (10.1%)
- Bottleneck still exists and remains above 100 seconds for this run shape.

## 2. Current Bottleneck Hypothesis

Primary hotspots:

1. FLS inference cost on large sentence sets
2. Repeated dense retrieval calls per record and per metric
3. Sentence volume from long SEC sections and chunking strategy

Non-hotspot:

- BM25 index construction is millisecond-level and not priority.

## 3. In-Scope Code Paths

- `forward_signals_text.py`
  - `_group_records_for_signals` loop across records and metrics
- `fls_filter.py`
  - `filter_forward_looking_sentences` and `_predict_keep_flags`
- `hybrid_retriever.py`
  - dense ranking path and query encoding
- `sentence_pipeline.py`
  - sentence split behavior and chunking side effects

## 4. Optimization Plan (No Feature Flag)

### P0. Add explicit stage timing (must-have first)

Add timing fields into final text pipeline diagnostics:

- `split_ms_total`
- `fls_ms_total`
- `retrieval_ms_total`
- `pattern_ms_total`
- optional per-record aggregates

Goal:

- Make subsequent optimizations data-driven and regression-checkable.

Expected impact:

- No direct latency reduction.

### P1. Reduce FLS input cardinality before model inference

Approach:

- Apply lexical forward-hint prefilter first.
- Keep lexical-hit sentences and their nearby context sentences.
- Hard cap max sentence count passed to FLS.
- Fall back to current behavior only when prefilter yields empty set.

Why:

- FLS currently pays full-model inference over many sentences.

Expected impact:

- Estimated 15s to 35s reduction on this workload profile.

Risk:

- Possible recall loss if prefilter is too strict.

Mitigation:

- Keep context window and validate signal recall on fixture set.

### P1. Dense retrieval throughput improvements

Approach:

- Disable progress bar in sentence-transformers encode calls.
- Batch all metric queries per record in one query-encode call, then dot-product in memory.

Why:

- Lower CPU overhead and log I/O noise.

Expected impact:

- Estimated 5s to 12s reduction on this workload profile.

Risk:

- Low. Logic-equivalent ranking path.

### P2. Long-sentence control in sentence pipeline

Approach:

- Split overlong sentences by punctuation/clausal boundaries.
- Bound per-sentence length before FLS and dense encode.

Why:

- SEC text often contains very long run-on sentences that degrade inference speed.

Expected impact:

- Estimated 10s to 25s reduction depending on filing text shape.

Risk:

- Medium. Over-splitting can hurt semantic coherence.

Mitigation:

- Keep conservative split rules and verify signal quality on fixtures.

### P3. Optional backend/model changes (only if needed)

Approach:

- Evaluate ONNX/FastEmbed backend for dense retrieval or smaller FLS classifier.

Expected impact:

- Potentially large, but requires quality regression testing.

Risk:

- Higher implementation and validation cost.

## 5. Target and Acceptance

Short-term target for similar workload (`records=6`, `analysis_sentences_total≈953`):

- `dense_to_text` from 110.8s to below 95s
- stretch target below 85s

Acceptance checks:

1. No regression in output schema and evidence fields.
2. No decrease in accepted-signal stability on existing test fixtures.
3. Log diagnostics include stage timings for each run.

## 6. Execution Order

1. Implement P0 instrumentation.
2. Implement P1 FLS input reduction.
3. Implement P1 dense query batching and progress-bar off.
4. Re-measure on real run and compare to `fa2.log`.
5. Implement P2 only if target not met.

## 7. Implementation Progress (2026-02-25)

Completed in code:

1. P0 instrumentation in `forward_signals_text.py`
   - Added:
     - `pipeline_split_ms_total`
     - `pipeline_fls_ms_total`
     - `pipeline_retrieval_ms_total`
     - `pipeline_pattern_ms_total`
     - `pipeline_fls_model_load_ms_total`
     - `pipeline_fls_inference_ms_total`
     - `pipeline_fls_sentences_scored_total`
     - `pipeline_fls_prefilter_selected_total`
     - `pipeline_fls_batches_total`
2. P1 FLS prefilter before model inference in `fls_filter.py`
   - Lexical forward-hint anchors + context-window sentence selection.
   - Hard cap via:
     - `SEC_TEXT_FLS_PREFILTER_MAX_SENTENCES` (default `120`)
     - `SEC_TEXT_FLS_PREFILTER_CONTEXT_WINDOW` (default `1`)
   - Throughput tuning:
     - `SEC_TEXT_FLS_MAX_LENGTH` default lowered to `192` (from `256`)
     - Added `SEC_TEXT_FLS_BATCH_SIZE` (default `32`) for minibatch inference
     - Added length-bucket batching (longer sentences grouped together) with output alignment preserved
3. P1 retrieval throughput in `hybrid_retriever.py`
   - Added `retrieve_relevant_sentences_batch(...)`.
   - BM25 sparse ranking now supports multi-query single-index pass.
   - Dense retriever supports `rank_many(...)` and batched query embedding encode.
   - Disabled sentence-transformers encode progress bar when supported.
4. `forward_signals_text.py` now uses batch retrieval per-record (single call across metrics).
5. P2 long-sentence control in `sentence_pipeline.py`
   - Added clause-boundary-aware long-sentence splitting before downstream FLS/dense.
   - Added hard-wrap fallback for unsplittable run-on text.
   - Added configurable cap:
     - `SEC_TEXT_MAX_SENTENCE_CHARS` (default `420`)
6. Startup prewarm for FLS classifier in `api/server.py`
   - Added `SEC_TEXT_FLS_WARMUP` (default enabled) during lifespan startup.
   - Warmup executes model load + one dummy inference to reduce first-request latency spike.
   - `docker-compose.yml` now sets `SEC_TEXT_FLS_WARMUP=1`.

Verification:

1. `ruff` on changed modules passed.
2. Targeted tests passed:
   - `test_sec_text_model_loader_circuit_breaker.py`
   - `test_sec_text_sentence_pipeline.py`
   - `test_sec_text_forward_signals.py`
   - Result: `28 passed`.

## 8. Notes

- This RFC intentionally avoids feature flags and dual-path runtime behavior.
- Changes are applied directly with tests and log-based verification.

## 9. FLS Optimization Checklist (Priority by Expected Gain)

Current observed bottleneck (run `481251f5-9094-4a1e-838e-25ab18e99acb`, `docs/logs/fa.log`):

1. `pipeline_fls_ms_total`: `67575.577` ms
2. `pipeline_split_ms_total`: `891.687` ms
3. `pipeline_retrieval_ms_total`: `1368.536` ms
4. `pipeline_pattern_ms_total`: `7.717` ms

Conclusion:

1. Retrieval is no longer the primary bottleneck.
2. Next phase must focus on FLS model path.

### P0. Measurement hardening (must do first)

Goal:

1. Separate model-load cost from inference cost.
2. Make cold-start vs warm-run optimization measurable.

Checklist:

1. Add `pipeline_fls_model_load_ms_total`.
2. Add `pipeline_fls_inference_ms_total`.
3. Add `pipeline_fls_sentences_scored_total`.
4. Add `pipeline_fls_prefilter_selected_total`.
5. Add `pipeline_fls_batches_total`.

Expected impact:

1. No direct latency reduction.
2. Prevents wrong optimization decisions.

### P1. High-ROI without model/backend switch

Checklist:

1. Lower sequence length cap from 256 to 192.
2. Add configurable FLS minibatch inference (`SEC_TEXT_FLS_BATCH_SIZE`, start from 24 or 32).
3. Length-bucket sentences per batch to reduce padding waste.
4. Tighten prefilter cap from 240 to 120 (initial trial), keep context window at 1. (done)
5. Add optional startup prewarm (load + 1 dummy inference) to reduce first-request latency spike. (done)

Expected impact:

1. FLS total latency reduction target: 30% to 50% for similar run shape.

Risk:

1. Recall regression if prefilter cap is too aggressive.

Mitigation:

1. Run fixture recall and compare accepted-signal stability before raising to production default.

### P2. Secondary gains after P1

Checklist:

1. Add in-run sentence-hash inference cache for repeated disclaimers/legal boilerplate.
2. Add per-form FLS cap (`10-K`, `10-Q`, `8-K`) instead of single global cap.
3. Add early lexical-only short-circuit when candidate set is very small and high-confidence.

Expected impact:

1. Additional 10% to 25% FLS reduction, workload-dependent.

### P3. Optional model-level changes (only if still above target)

Checklist:

1. Evaluate smaller FLS classifier variant (HF model swap only, no ONNX path).
2. Keep single-path runtime; no feature flag.
3. Require quality gates before adoption.

Acceptance gates:

1. No schema regression in forward signal payload.
2. Fixture precision non-decreasing.
3. Fixture recall drop no more than 0.02 (absolute) unless explicitly approved.

### Verification commands

Run benchmark in backend container:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=/app:/app/src /opt/venv/bin/python scripts/benchmark_sec_forward_signals.py --iterations 8'
```

Extract latest forward-signal pipeline metrics from log:

```bash
rg -n "fundamental_forward_signal_text_producer_(completed|no_signal)" docs/logs/fa.log -S | tail -1
```

Confirm model backend and load status:

```bash
rg -n "fundamental_fls_filter_model_loaded|fundamental_hybrid_retriever_dense_loaded" docs/logs/fa.log -S | tail -20
```
