# SEC Inline XBRL document sets

An annual report can put cover facts in its primary document and financial facts,
schema references, and shared contexts in an exhibit. Acquisition therefore selects
the complete default-target Inline XBRL document set from the SEC full submission.
It does not choose documents by issuer, accession, or exhibit number.

`inline_xbrl.py` owns the bounded inventory and canonical input manifest.
Acquisition owns retrieval, ingestion owns original-byte assessment and staging,
and Arelle owns XBRL interpretation and regulatory validation. Accounting mapping
and valuation formulas retain their existing owners. Automatic mapping policy
`source-bound-us-gaap-v36` includes the document-set implementation in its digest.

## Evidence and replay

Each member must be uniquely indexed and captured independently. Ingestion checks
the complete ZIP inventory against the full-submission selection, applies the
existing direct-response/index/archive byte policy to every member, and retains
original and parser bytes. A sorted canonical manifest binds every parser member's
filename and content hash. Its digest is the parser input identity; the primary
document's original hash remains separately available.

The pinned Arelle IXDS plugin parses the manifest as one default target, including
cross-document contexts. SEC EFM/DQC and offline validation requirements remain
mandatory. Validation evidence binds the manifest digest. Trusted release
verification independently inventories the retained ZIP and repeats each member's
byte checks, rejecting omitted, changed, or falsely single-file evidence.

Metadata scanning uses XML namespaces and Arelle-compatible XML recovery, rather
than HTML raw-text or implicit depth truncation. It interprets no fact values.
Explicit depth and node limits reject excessive structures. Tests include inline
nodes deeper than the HTML parser limit and inside XHTML script/style elements;
inventory recognition does not exempt such documents from regulatory validation.

## Supported scope

Support is limited to one default target, one local indexed schema, and 2–8 root
HTML/XHTML members. Named targets, foreign schema references, inherited XML base
URIs, unsafe or repeated names, incomplete inventories, and excessive inputs fail
explicitly. Limits include 24 MB per document/archive, 48 MB per inline set,
64 MB per full submission, 4,096 archive/submission members, 256 MB expanded ZIP
content, XML depth 512, and one million XML elements per document.

This capability preserves multi-file originals. It does not prove accounting
component completeness, complete awards, supported model eligibility, market-data
permissions or a successful numerical valuation. Regulatory
completion mocked in boundary tests is not real release-gate evidence.

## References

- [XBRL Inline XBRL 1.1 specification](https://www.xbrl.org/Specification/inlineXBRL-part1/REC-2013-11-18/inlineXBRL-part1-REC-2013-11-18.html)
- Pinned Arelle `plugin/inlineXbrlDocumentSet.py` for JSON IXDS entrypoints and
  `ModelObjectFactory.py` for XML parsing semantics.
