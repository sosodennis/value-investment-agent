# Current BEA GDP source preparation (#361)

Implementation: `37acaec3a4b60a84d9ea5da1fd6b9fa2d79a0a7c`.
This checkpoint verifies the maintained current BEA NIPA workbook through the
registered `PublicSourceAdapter`, immutable `PublicSourceAcquisition` cache,
versioned source-use admission and the existing nominal-GDP growth ceiling.
It is source preparation evidence, not full valuation or history-threshold
approval.

The captured admission below is a historical checkpoint under
`free-market-source-use-v4`. The current policy is
`free-market-source-use-v5`: it retains the original terms-page digest and
pins the exact BEA citation article with an `exact-html-element-v1` scope.
Replaying this evidence under v5 must use the retained original bytes and
record both the whole-page and selected-article digests; this historical report
is not a current v5 admission.

## Captured source

The exact source is
`https://apps.bea.gov/national/Release/XLS/Survey/Section1All_xls.xlsx`, source
`bea-nipa-current`, profile `bea-current-nipa-gdp-capture-v1`, captured and
available at `2026-11-13T10:39:51.061613Z`. Its retained workbook is **4,067,847**
bytes with SHA-256
`a920921a004910f973021dc89236f11fca5120fadefcaba4a8e1ff55f7625e2d`.
The provider reproduced **97** annual observations from 1929 through 2025.
Only the actual capture timestamp establishes availability; this source cannot
be selected for an earlier valuation.

The source-use decision is `admitted` under `free-market-source-use-v4`, policy
digest `bac02047aea49306c48ef045eb5af4178dc143ca2ba4825e36205571e8c8ae68`,
with no issue codes. It verifies the retained BEA citation terms digest
`362a0e376b235df1333aea67d3eb4d4cc103fd754d056d1a5950449bdc99b04f` and U.S.
Government Works terms digest
`be9a8a2918c3f674506e80087565ce9f5479ea358394313daf02e3aa0a1491ba`.

The existing `nominal-gdp-cagr-ceiling-v1` helper reproduced a 10-year nominal
GDP CAGR of `0.0536785130963225133099248796844361847462899872342` for 2015–2025,
with content digest
`63b651d262283856a1f462048bd7e402838f16e32856e87e3f153817abd7e4db`. This is
only the GDP-side ceiling input; the terminal-growth policy still combines it
with the separately admitted long-term risk-free rate.

## Replay evidence

The frozen request digest is
`74a2346e5b43d7da30adb9eea4d95ba09f949dd8f2eb80c1eb39556c75f90b2d`; reproduced
source input digest is
`d106e9e1a2b43008aa994abaf761959b0ee0f16cf02fabeb466810a368e10b9a`; reproduced
source output digest is
`d25a5dc9dc4c19a23a293687639e827459abf8085b9e1effaae7d6b5ed1d6525`.
The first request made one HTTP call and wrote the immutable receipt/original.
The same-process repeat returned `wrote=false`, made zero HTTP calls, and left
the artifact/content inventory unchanged. A second fresh Python process used the
same request and returned `wrote=false` with zero HTTP calls on both executions;
the inventory and output digest were unchanged.

Cold-capture proof digest:
`68ac199931c7502441a518985ea06e66b2c7b36b904f331edd1830ffde1a1b6a`.
Second-process proof digest:
`95631523f793cb9165fbbc24d95e8ef73aaba93d97ef40229b9f6c9d054c6072`.
Acceptance report output digest:
`431b437bc6975832248940af2fb522b8c40c6eccfa66de9b9fa3e650511d8370`.
The raw workbook, canonical request, acquisition receipt, proofs and report stay
outside Git under `.audit/issue-361-bea-current-source-preparation/`.
Verification driver SHA-256:
`72cef902f29e643900be79ac812294b5eb5d92f97335a5e7a22a5c7efc4f6d49`.

## Verification and limits

Command: `fundamental-service/.venv/bin/python -B .audit/issue-361-bea-current-source-preparation/verify.py`.
Tests: `uv run --directory fundamental-service pytest -q tests/test_bea_source.py tests/test_public_source.py tests/test_public_acquisition.py`;
**125 passed, 1 optional skip**. Pinned Ruff 0.14.10 lint and format checks
passed; `git diff --check` passed.

The initial acquisition request was timestamped before the HTTP response, so its
receipt retains `SOURCE_NOT_AVAILABLE_AT_VALUATION`. Admission and the ceiling
were evaluated at the actual capture timestamp, where the source is available.
No earlier availability is inferred. This source-only result does not complete
the full numerical flow, does not change quality status, and leaves
`supported_history_threshold=null`.
