# Frozen label inventory audit (#376/#377)

`scripts/audit_history_study_labels.py` reconstructs the label selection for all
100 fixed issuers from their original hash-pinned normalized SEC snapshots.
It does not execute forecasts or acquire replacement filings. The unchanged
cohort has manifest digest
`448f496b10e51a2ed351a7a37deb36e0d4b9672c1fbc5ed3b0b845c8cd54da3a`.

The command checks the embedded original-inventory digest and all 100 compressed
snapshot hashes, then binds each snapshot to its issuer, decision accession and
UTC availability. It calls Fundamental Service's existing
`first_subsequent_original_filing` function. That policy considers the earliest
later annual period, then its first original 10-K. An amendment-only earliest
period cannot be replaced by an original for a still later period. Duplicate
accessions and equally available first originals fail rather than resolving by
file order.

Recomputed label accessions, period gaps and missing reasons must equal the
frozen manifest. Horizon eligibility is retained from that manifest; this audit
does not introduce a new tolerance or infer a mismatch from a null horizon.
Every issuer remains in the report, including all its annual inventory rows,
amendments, later candidates, selected label, source-response metadata and
snapshot digests. Corrupt or missing inputs fail before publication.

## Meaning of the result

The retained 100 snapshots contain 1,931 normalized annual filing rows. They
reproduce 90 eligible frozen labels, one selected label with a 731-day gap, and
nine issuers with no later annual period in their retained snapshot.

This is evidence about **the retained normalized inventory**. Source-response
metadata preserves the SEC URI and raw-response digest, but the audit does not
reconstruct normalization from raw responses or independently prove SEC search
completeness. It therefore cannot attribute missingness to acquisitions,
deregistration, survival or company failure. The missingness mechanism remains
unestablished. A normalized snapshot's declared response hash is not a new
verified raw-response capture.

The 90 count is the maximum under the frozen inventory and horizon flags, before
mapping, accounting, label-quality, model or source-release gates. It is not 90
verified FCFF labels or completed forecasts. Neither missing labels nor a
successful audit change the legacy sample gate or permit threshold promotion.
`source_completeness_verified=false`, `mapping_or_release_approved=false`,
`forecasts_executed=0` and `supported_history_threshold=null` remain explicit.

## Run and repeat

Use a clean exact commit and the same pinned Python runtime. The existing 100
snapshot files may be copied to an explicit external evidence directory; their
compressed bytes must remain identical. No historical or generated data needs
to be added to Git.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=fundamental-service/src:scripts \
  python -B scripts/audit_history_study_labels.py \
  --manifest /absolute/external/fixed100-manifest.json \
  --snapshot-directory /absolute/external/frozen-snapshots \
  --exact-commit <full-clean-implementation-sha> \
  --output-directory /absolute/external/label-audit
```

The report binds the exact commit, manifest bytes/canonical digest, all snapshot
digests, selection/decoding/publication/tool source digests, lock digest and
runtime. Paths are locators and do not become data identity. Publication uses
the existing canonical JSON serializer and locked temporary-file/fsync/atomic
rename publisher. Repeating the command returns the same report/input/output
digests and `wrote=false`, retaining existing bytes, sizes and modification
times. It has no network fallback, database, Docker or signing side effects.
