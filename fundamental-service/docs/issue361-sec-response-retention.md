# Original SEC response retention for #361

Pinned-accession production acquisition uses `RetainedSecSourceAdapter` before provider I/O. Decision receipts are keyed by the versioned receipt protocol, normalized CIK, original accession, valuation timestamp, source-selection policy and exact URI. For canonical SEC Archive resources beneath that accession path, an additional immutable original-response receipt is keyed by CIK, accession and exact URI, independent of valuation date or source profile. Mutable submissions and other endpoints remain decision-scoped. Captured time is receipt metadata, never identity.

The service stores exact response bytes by content hash and an immutable canonical receipt in its existing content/artifact stores. Receipts retain status, media type, original capture time, retained response headers and declared/received sizes. PostgreSQL advisory locks serialize capture for the same key before checking the receipt or downloading. A contending request receives a retryable error. The acquisition lock still protects snapshot publication separately.

A retry or process restart reads the applicable receipt and verifies its identity, URI, artifact state, content hash and byte length. Valid receipts produce no content/artifact writes. Corrupt or missing retained bytes fail closed instead of silently fetching replacement bytes. Partial upstream response failures do not produce a successful receipt; a later attempt may retry provider I/O. The original bytes and shared receipt are committed before the decision receipt, so a crash in between reuses the retained response without another provider request. Content-addressed storage prevents duplicate retained evidence.

`SecAcquisitionUseCase` passes the retained adapter into the existing ingestion service for the index, original entrypoint and accession ZIP. For an unpinned latest-filing request, SEC submissions are read first to select an accession; the adapter is installed after that selection and before index/package acquisition. The request-local adapter avoids mutating shared ingestion state. Stable original receipt times determine the acquisition capture time. A later parser or mapping rejection therefore retains the same raw evidence for another attempt. The runtime factory uses the existing PostgreSQL content/artifact stores; it does not need new volumes, migrations or credentials.

This change does not approve mappings, establish historical security identity, publish failed snapshots or bypass regulatory validation. The separate [original-filing identity contract](issue361-historical-identity.md) avoids present-day ticker membership only when original DEI security evidence can be checked; complete2016 cover-page support remains an open #371 gap. Original sample diagnostics use an explicitly nonpublishable CIK-bound identity and do not establish a canonical replay. Full fixed-cohort replay and thresholds remain unapproved. Full acquisition `execute()` still records per-attempt operational audits; this source-reuse evidence does not establish idempotency of those rows.

## HTML tag-line padding

The versioned `sec-edgar-html-tag-line-padding-v1` relation handles an additional
SEC delivery representation: ASCII spaces/tabs removed immediately before LF on
otherwise blank or tag-ending lines. It requires the original accession-bound
index and ZIP, an HTML primary filename, expected Akamai response metadata and
the exact existing terminal-script shape. Removing that script must reproduce
the indexed primary size. Removing only the declared line padding from the ZIP
member and appending exactly one terminal LF must reproduce every remaining
direct-response byte. CR, Unicode whitespace, changes to leading/interior or
ordinary text-line whitespace, and any substantive byte change are unsupported.

The parser receives the unchanged original ZIP member, including all its
padding. Raw/index/ZIP/member hashes and raw removed script/LF ranges remain in
integrity evidence. The rule signature also binds every archive-padding byte
range and its hash. Existing exact, terminal-script and XML relations retain
their policies and digests. Regulatory validation and original-versus-parser
fact/finding comparison still apply; this relation grants no mapping approval,
trusted release, numerical valuation or history threshold.
