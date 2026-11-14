# Original filing identity for history replay

`SecIngestionRequestV1.identity_basis` selects the identity evidence policy.
`current-sec-ticker-v1` is the default and retains the existing SEC submissions
ticker check. `original-filing-dei-v1` requires a pinned original `10-K` accession;
it checks the submissions CIK without consulting its present-day ticker list.
The original filing still passes all byte-integrity, offline EFM/DQC and
point-in-time source gates before identity or canonical publication.

Original identity must match the requested CIK, registrant name, ticker and
security title using explicit original DEI facts. The security ID is the filed
ticker; the requested share class must equal the filed `Security12bTitle` after
whitespace/case normalization. The requested ticker must identify exactly one
original security context. Its title must share that context ID, period and
dimensions. The context may be issuer-wide or have exactly one
`us-gaap:StatementClassOfStockAxis` member. Other listed securities remain in
the audit evidence; their titles cannot establish the requested class.
Absent, conflicting, cross-context or unsupported dimensional evidence fails;
the policy does not infer a common class from issuer-level shares outstanding.
The original document type/period, context issuer/scheme, DEI namespace,
domestic incorporation and USD US-GAAP evidence are checked as well. Currency
requires unambiguous monetary units from consolidated, dimensionless facts at
the original report end; a USD subsidiary, older-period fact or USD/share unit
cannot establish the reporting currency.

The parser now retains each fact's namespace URI. A `dei:` prefix alone cannot
establish SEC DEI provenance. This additional semantic field changes parser
fact/report digests; evidence from an older source commit is not reused as
verification of the new implementation. Existing retained HTTP receipts remain
valid original bytes and need no replacement download.

The service retains matched and refused identity evidence under a canonical
content digest, including the accession, original source hash, parser digest,
validation profile, requested identity, actual DEI facts and exact refusal
reason. A refusal raises `SnapshotError` with its evidence reference before
snapshot/fact publication. A successful acquisition returns the reference in
`SecIngestionResponseV1.identity_evidence_ref`. Repeating the same evidence
reuses its artifact without modifying its bytes or mtime.

This contract does not establish that the fixed 2016 cohort has the required
DEI security facts. Missing original facts remain `HISTORICAL_IDENTITY_MISSING`;
ambiguous ticker contexts remain `HISTORICAL_IDENTITY_CONFLICT`, and unsupported
dimensions remain `HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED`.
Reviewed original cover-page evidence would require a separately validated
policy; current ticker/survival data is not a fallback. A prior regulatory
validation rejection remains the primary failure and cannot be bypassed by
identity matching. This identity policy does not approve accounting mappings,
historical market policies, data releases or history thresholds.

## Historical applicability research

The SEC's [April 22, 2019 compliance guide](https://www.sec.gov/resources-small-businesses/small-business-compliance-guides/fast-act-modernization-simplification-regulation-s-k),
read directly for this engineering investigation, describes the March 20, 2019
amendments. It states that registrants "will be required to disclose" the
trading symbol and security class title on the cover page, and "will be
required to tag all cover page data" in Inline XBRL. Its phase-in table gives
fiscal-period cutoffs of June 15, 2019, 2020 and 2021 for the respective filer
categories. The guide links the adopting release,
[33-10618](https://www.sec.gov/rules/final/2019/33-10618.pdf).

This explains why requiring modern security DEI tags cannot establish complete
2016 identity coverage. It does not prove those tags are absent from every
issuer's original, nor that an issuer lacked a security at that time. Original
cover-page/class evidence needs its own supported historical policy before
those cases can publish canonical security-bound snapshots. This research is
engineering compatibility evidence only, never threshold ground truth or an
accounting/policy approval.
