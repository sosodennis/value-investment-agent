# Submission-corroborated HTML representation

The SEC original integrity policy can reconstruct an unchanged official ZIP
HTML member from a direct response with line-end padding removed. This applies
across issuers and accessions. It does not change any parsed financial value or
permit general whitespace normalization.

The existing rules cover blank/tag-ending lines and the exact `&#160;` layout
suffix. Other text-line suffixes require all of the following evidence:

- The index and ZIP belong to the same accession and the indexed ZIP size matches.
- The direct response has the existing Akamai metadata and terminal script shape.
- Removing that one script produces exactly the indexed primary size.
- Removing every ASCII SP/TAB suffix immediately before LF in the ZIP member,
  then appending one LF, produces every script-free direct-response byte.
- The complete, bounded SEC submission has the matching accession header and
  URI, a unique primary filename, and an HTML body equal to those same bytes.

`sec-edgar-submission-html-line-padding-v1` binds the submission hash and all
padding offsets/hashes in its rule signature. The optional submission hash is
retained on the primary or individual Inline XBRL member integrity record.
Original preparation requires its exact capture receipt; mapping and trusted
release repeat the rule from retained bytes. Missing or changed evidence refuses.

The parser consumes the untouched ZIP member, and existing EFM/DQC gates remain
mandatory. A complete original and a passing byte proof do not establish
accounting scope, award completeness, mapping correctness or valuation readiness.
Automatic mapping policy `source-bound-us-gaap-v37` pins the executable change.
