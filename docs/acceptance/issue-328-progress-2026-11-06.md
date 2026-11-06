# Issue #328 SEC Artifact Integrity Evidence

Issue: [#328](https://github.com/sosodennis/value-investment-agent/issues/328)
Branch: `codex/issue-328-sec-integrity`
Base: `codex/issue-312-sec-ingestion` at `18771b9d14baa245f1676d9deb6c9b42ab9df56d`

## AAPL Accession Classification

Accession `0000320193-24-000123` belongs to CIK `0000320193`. SEC's public
accession `index.json` identifies the primary document as
`aapl-20240928.htm` with declared size 1,503,780 bytes, and the accession XBRL
archive `0000320193-24-000123-xbrl.zip` with declared size 458,550 bytes.

The following public responses were captured on 2026-11-06. The direct filing
response was fetched twice with the same SEC User-Agent. The second retrieval
was used to check that the byte-level classification reproduces. No response
cookies or credentials are recorded here.

| Artifact | HTTP status | Declared bytes | Received bytes | SHA-256 |
| --- | ---: | ---: | ---: | --- |
| SEC accession index JSON | 200 | not returned | 2,431 | `556272b4254475f458cdf6395db66c5aaee90d0a0618dc429767bfe96a75bace` |
| Direct primary-document response, retrieval 1 | 200 | no `Content-Length` header | 1,503,899 | `59e335a7f96c51b4ec356026f6cdabbdd0b2589fe816d7c7b7d33521db8b16c4` |
| Direct primary-document response, retrieval 2 | 200 | no `Content-Length` header | 1,503,899 | `59e335a7f96c51b4ec356026f6cdabbdd0b2589fe816d7c7b7d33521db8b16c4` |
| SEC accession XBRL ZIP response | 200 | 458,550 | 458,550 | `c19944b22ee101abbfd69b2e6fa4f30e0ec511ad276fdbb3cf3ef5dce3938fee` |
| Primary document member extracted from ZIP | archive member | 1,503,779 | 1,503,779 | `a051b50fcba8c752df3dd55a87f42e0fb1c8f31b7b8ed287f55c8c385849e159` |

The direct response has one trailing script element immediately before
`</body></html>` and a final line feed. The response includes the SEC edge
header `x-akamai-transformed: 0 - 0 -`; the archive response has
`cache-control: no-cache, no-store, no-transform, proxy-revalidate`. The
accession ZIP's primary member has no script element.

For both captured direct responses, deleting only the exact trailing script
element and final line feed yields 1,503,779 bytes that compare byte-for-byte
equal to the primary document member in the accession-matched ZIP. This
establishes that the script is added to the direct HTTP representation and is
not part of the canonical primary document distributed in the SEC XBRL ZIP.
The existing committed AAPL direct-response fixture has a different
script-path value; that is why normalization must be constrained by the
accession ZIP bytes and a narrow versioned rule, not by ignoring arbitrary
`<script>` elements.

The classification evidence is not permission to publish a filing after
normalization. #328 must persist raw response and archive evidence, record an
allowlisted normalization manifest binding raw and output hashes, prove exact
XBRL semantic equality, bind the pinned offline Arelle EFM/DQC report to the
normalized input and taxonomy manifest, and publish no selectable snapshot or
facts until every integrity and parser gate passes. Unexpected differences
remain fail-closed.

## Commands and Results

- `curl -fsSL --retry 2 -A 'Value Investment Agent contact@example.com' -D <headers> '<direct filing URI>' -o <raw response>`: exit 0 for each of two retrievals.
- `curl -fsSL --retry 2 -A 'Value Investment Agent contact@example.com' -D <headers> '<accession index URI>' -o <index JSON>`: exit 0.
- `curl -fsSL --retry 2 -A 'Value Investment Agent contact@example.com' -D <headers> '<accession XBRL ZIP URI>' -o <archive>`: exit 0.
- `unzip -p <archive> aapl-20240928.htm > <archive member>`: exit 0.
- Python `hashlib.sha256`, ZIP member extraction, exact suffix comparison, and `bytes` equality check: exit 0; both direct-response normalizations exactly equal the ZIP member.

No production parser or source implementation was modified for this
classification checkpoint. Arelle acceptance and Docker health have not yet
been rerun for #328. This is evidence of response origin only; publication
remains fail-closed until the implementation and acceptance suite are
complete.
