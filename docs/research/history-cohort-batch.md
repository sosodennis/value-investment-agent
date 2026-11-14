# Fixed-cohort original evidence batch

`scripts/batch_history_study.py` turns the frozen #376/#377 original filing
records into source-bound mapping review packets. It retains all 100 issuers
and 589 targets. It also replays explicitly supplied conditional comparison
seeds through the existing three/four/five-year runner and formal Fundamental
Service composer. A candidate packet cannot create an approved mapping,
trusted release or exact model input. The threshold remains null.

The first10 mode uses ascending canonical CIK order, independent of parser
success or forecast outcome. It reports the other90 as unprocessed. Full100
uses the same issuer artifact identities; batch size is not issuer identity.
All filing roles and original failure codes remain in each issuer packet,
including failures superseded by explicitly supplied newer evidence.

## Inputs

Use the fixed canonical manifest with SHA-256
`448f496b10e51a2ed351a7a37deb36e0d4b9672c1fbc5ed3b0b845c8cd54da3a`.
The retained source repository must contain exact commit
`32be2dafbbc7756bf185e228dc8fdcc280fe6cf3` from the preserved research bundle.
The reader uses only explicit pinned references, validates gzip/chunk content,
length, canonical JSON and original envelope digests, and never restores files
or scans for the latest result. The underlying parser execution remains
`62f121f386534ea65f0be15b04efc83ed4478d09`; decoding a retained report does not
rerun Arelle or establish current regulatory approval.

A canonical `history-study-batch-index.v1` JSON document contains:

- `fixed_manifest_digest`: the fixed manifest digest above.
- `source_revision`: the exact preserved commit above.
- `runtime`: the tuple returned by `export_history_study_evidence.runtime_pins()`.
- `originals`: zero or more `{path, sha256}` references to current typed
  `OriginalIssuerEvidenceV1` documents, at most one per fixed accession.
- `seeds`: zero or more `{path, sha256}` references to longest-history
  `OperatingComparisonRequestV1` documents, at most one per fixed issuer.

Paths resolve relative to the index directory; absolute explicitly supplied
paths are supported. Each file must have canonical bytes matching its digest.
Runtime mismatches, duplicate/foreign issuers or sources, changed decision dates,
accessions, periods, amendments or available-at times fail closed. Conditional
seeds additionally pass the existing formal exporter, including its original
label, source-selection, history-arm and model/policy checks. Current originals
supplement archived outcomes; they do not remove the earlier refusal record.

The mapper exposes only alternatives already declared by the owning service's
rule table. It preserves every candidate period, unit, dimension, scope,
accession, provenance and stable fact identity. Candidates remain provisional;
D&A/capex scope, operating partitions, extension concepts and missing categories
still require their actual accounting evidence. A missing candidate says only
that the supplied report/proposal yielded none, not that a financial amount is
zero. Parser blockers are retained and prevent candidate construction.

## Run and repeat

Run at a clean exact implementation commit with the pinned interpreter and
`PYTHONPATH=fundamental-service/src:scripts`:

```sh
python -B scripts/batch_history_study.py \
  --manifest /absolute/evidence/fixed-manifest.json \
  --index /absolute/evidence/batch-index.json \
  --source-repository /absolute/preserved-history-reader \
  --exact-commit <full-SHA> --limit 10 \
  --output-directory /absolute/evidence/batch-output
```

Then run with `--limit 100`, followed by the identical full100 command again.
Generated sources, packets, formal outputs and report are written outside every
Git checkout by the existing locked, temporary-file/fsync/atomic-rename
publisher. Identical bytes are reused without rewriting. The CLI reports
`wrote=false` and `artifacts_written=0` on an unchanged repeat. A partially
published prefix is safe to resume: completed content digests are reused.

Report inputs bind the exact commit, canonical index, manifest and runtime.
Each issuer's input digest additionally binds its explicit archived and current
source references, seed and mapping policy. Its output digest binds retained
filing outcomes and every model/history arm. Absent seeds produce six explicit
abstentions. Conditional arithmetic remains excluded from exact study losses;
scenario/model/history rows do not increase the independent issuer count.
