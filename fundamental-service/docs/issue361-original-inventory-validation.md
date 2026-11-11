# Fixed original filing validation

`history_original_validation` expands the unchanged #359 cohort and frozen filing
inventory through the existing point-in-time selection policy. It retains all
100 issuers, 589 relevant filings (541 original 10-K and 48 amendments), and the
nine missing first-subsequent original labels. Each history filing keeps the
fixed decision cutoff; each first original label keeps its own acceptance time.
No issuer, decision date, amendment or unavailable label is replaced.

The composition script `scripts/validate_fixed_history_originals.py` uses the
configured PostgreSQL/content stores and the existing retained SEC adapter and
ingestion `prepare_filing` path. It requires exact installed source hashes,
executor hash, commit and runtime pins. SEC requests use the configured contact
and shared provider pacing. The validation profile, taxonomy cache, parser
resource limits and request policy are pinned in every input digest.

Original index selection requires one standalone XML instance and its matching
schema. Missing/ambiguous/inline-only packages are retained as refusals. This
selection policy is diagnostic and does not establish historical security
identity. Original source bytes, accession, period, form, amendment flag and
available-at cutoff remain traceable. Successful parser reports keep facts,
contexts, units, scopes, namespaces, source hashes and validation evidence.
Refused parses keep their stable error code and original retained diagnostics.

The script supplies an explicitly diagnostic identity, no accounting mappings,
and a repository that rejects canonical publication. `prepare_filing` creates
only an unpublished in-memory candidate after its integrity/EFM/DQC gates.
No snapshot, canonical fact, acquisition or release is published. A successful
validation does not approve a security identity, accounting mapping or model.

Per-target results use canonical input/output digests. The controller holds a
PostgreSQL advisory lock across lookup/evaluation/publication, and both passed
and refused observations are retained. Repeating the same inputs reads those
results without a provider request, parse or audit append. Transient provider
failures describe the frozen acquisition attempt, not missing historical SEC
facts; a new acquisition attempt requires a separately declared source protocol
or changed runtime inputs. Programming errors abort and are not financial
observations. Existing matching reports are reused with `wrote=false` through
the shared atomic content-addressed writer.

Run inside the isolated service container with the frozen cohort files and a
runtime-pin document prepared from the exact Git commit:

The cohort root must also contain the original protocol, frame manifest and its
two digest-checked compressed frame files. Selection is recomputed from that
explicit root, including when installed outside a repository. Missing frame
evidence fails before any provider request; it never falls back to another
checkout. A deployment regression at checkpoint `c8a67a24` exposed the old
helper's implicit repository-root dependency before any SEC acquisition.

```sh
python /tmp/validate_fixed_history_originals.py \
  --cohort-root /tmp/issue361-fixed-cohort \
  --runtime-pins /tmp/issue361-original-runtime-pins.json \
  --output-directory /var/lib/fundamental/fixed-original-validation-v1
```

This is original-source coverage evidence. It does not execute forecasts,
complete independent review, approve historical policies, or establish a
supported history threshold. Full release-bound composer replay remains a
separate #361 acceptance gate. Preserve retained original bytes and their
metadata before any eventual issue-owned volume cleanup.
