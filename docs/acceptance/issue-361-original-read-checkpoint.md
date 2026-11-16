# Original preparation read checkpoint

This is partial #361 engineering evidence. M1, M2 and M3 remain incomplete;
PR #370 remains draft. No numerical valuation or caller approval is claimed.

## Exact `8631d382` real workflow

The installed SEC-enabled project `value-investment-agent-361-current-issuer`
uses ports 21471/21472. Its fixed MSFT CIK/date diagnostic configuration excludes
the quote and cannot qualify as the complete valuation configuration.

The first v15 command reached the 900-second issuer deadline after entering
automatic release/content verification. All 12 observed parser workers exited
zero; the HTTP-denial guard recorded no attempt. Input/output digests:

- `ad4232c5f2a4a2989655c686f41bff19c08965b4b41c53498142060db50cdab7`
- `10ade023e459cff49031b63c553361d7b94ad07d4513e858c047bea782137282`

The unchanged command resumed in 269.33 seconds. Its authenticated report
retains `DILUTION_QUOTE_ADMISSION_MISSING`; preparation and calculation are null.
The report content digest is
`b3345e5a7efbfd603c14c22f5aab03ed6863159356fafae8c7c6d370431cc3d2`.
Authenticated retrieval returned 200 and unauthenticated retrieval 401.

Acquisition, snapshot, fact, mapping and release rows stayed byte-identical
under ordered PostgreSQL row-JSON SHA256. Three previously unfinished binding
and report artifacts were added. A further unchanged command completed in
281.83 seconds with the same report and `wrote=false`; all 15 inventoried tables,
including artifact/content metadata, had identical counts and row-set digests.
The final inventory output digest is
`45f0b69134aa1ff4fdd1f8d9a392f5ec77cc9634e8e79ea2830133c2583e88af`.
No additional parser worker or HTTP attempt occurred during either continuation.
This establishes blocked-flow resumption and reuse, not numerical replay.

The first preparation process's 61 ten-second samples recorded 3,703 logical
artifact reads, 23,183,034,691 bytes and 28.33 seconds in the reader. These are
logical bytes and inclusive samples, not physical disk use or a complete CPU
profile. They do not establish that reducing reads alone fixes the deadline.
CI run 43798744281 passed 12 executed jobs; its release gate was skipped.

## Selected original reuse

Owner: Fundamental original preparation and SEC acquisition. The existing full
preparation read already validates every original, receipt, source, dependency,
annual selection and request. SEC acquisition then read the individual
validations again while locating its accession.

`read_with_validations` returns both preparation and the typed validations it
checked during that read. Acquisition selects from these results in the same
strict order. Consumers needing only preparation retain `read`. Each new
operation repeats the existing checks. There is no global cache, serialized
trust flag, public wire change or change to valuation policy and formulas.

The cold/completed regression first reproduced two validation reads instead of
one. The changed path reads once per original, revalidates on the next call and
rejects subsequently corrupted source bytes. Existing runtime, identity, cutoff,
receipt, missing-source and dependency refusal checks remain enabled.

On the retained real three-original MSFT preparation, two local samples in the
same container measured six validation reads at 6.09–6.38 seconds before and
three reads at 3.08–3.11 seconds after. Both selected-file digests remain
`f692f7688533bc110b77c821ffb733a92863add73f730481159bc3ce43bba3e5`.
This small sequential comparison measures this read only, not full performance.

Working-tree checks passed 512 owner/PostgreSQL/recovery tests and 56 formal
caller tests with zero skips, Ruff/format, types in 18 owners, both architecture
guards and diff check. The unique test database was removed. Independent
read-only review of the three code/test files reported no findings; it did not
review the whole PR or certify end-to-end behavior.

Git-external receipts, exact commands and complete reports are under
`.audit/issue-361-current-issuer-service/`, with prefixes
`8631d382-v15-`, `8631d382-msft-retained-market-release-mapping-v15` and
`8631d382-prepared-original-`. The WIP check input/output digests are
`651209bd927dd9966b9da443c74740c39ecf5edf8d69b5dacb97dd114d289efa` /
`894cb0145c59231944840e35ce810a5314bbe92904a0a22b8fae2528993b739e`.

Next: exact-commit checks and installed parity, then a complete process/child
CPU and wait profile of the real path before designing broader bounded reuse.
Quote permission/admission, full release, real caller approval, numerical
restart/restore and final release acceptance remain outstanding. The supported
history threshold stays null; #376's cohort is unchanged.
