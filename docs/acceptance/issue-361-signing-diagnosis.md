# #361 project signing and historical input diagnosis

Observer/checkpoint source: `1c665bacce3a1fbe877b3433d4400e8839557f8e`. The verified implementation remains `9a757bcd2ea144c216d520b78e5271f4d4193b00`; this checkpoint changes acceptance evidence only. `origin/main` is `52e84dfe5a0dae0c11d2e62fd9a58e885b6eadc9`, already an ancestor of the issue branch. A normal `git merge origin/main` returned `Already up to date.` Existing WIP commits remain intact.

## Signing is operational

The requested [project signing CLI](../../fundamental-service/docs/issue361-project-signing.md) already exists in [history_review_signing.py](../../fundamental-service/src/fundamental_service/history_review_signing.py). Its commands initialize/reuse the persistent project key, seal mapping/policy proposals, sign completed independent mapping reviews, and verify signatures against a separately pinned public identity. No new signer identity is needed.

At the observer commit, all 11 signing tests pass. Both existing mapping and market-policy proposal seals verify against their exact subjects. Two `init-key` executions return `key_wrote=false` and identity `wrote=false`; the key retains its mtime and mode 0600 and reuses the pinned public identity. Proposal seals continue to record unapproved status. No completed semantic review or historical policy approval has been inferred from the user's authorization to use project signing.

## Why signing and parser retries cannot finish this replay

The [existing exact-100 readiness inventory](issue-361-cohort-root-evidence.md) already establishes zero complete candidate decision origins for either model, even if every existing candidate were approved. Ten FCFF roles lack eligible Company Facts candidates in every issuer; transition also lacks filed operating evidence. This counts gaps in the captured candidate profile, not absence from original disclosures.

Two official sources explain why that profile cannot establish universal historical coverage:

- The [SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) explicitly limits aggregated XBRL facts to non-custom taxonomies and facts applying to the entire filing entity. Company Facts therefore cannot stand in for original custom concepts, dimensional/security-class context, or the original instance's context and fact IDs. This text was read directly in the browser. A separate urllib request returned HTTP 403; no raw HTTP receipt is claimed for that observation.
- [FASB ASU 2016-02 Section A](https://storage.fasb.org/ASU%202016-02_Section%20A.pdf), printed page 7 / PDF page 13 and paragraph 842-10-65-1(a), makes Topic 842 effective for public-entity fiscal years beginning after December 15, 2018, with earlier application permitted. The current service profile's recognized operating/finance lease inputs cannot be presumed present in a 2016 filing. Each issuer's actual accounting regime must be inspected. A legacy operating lease commitment is not automatically a recognized lease liability, and an absent modern tag is not a reported zero.

The FASB PDF's complete bytes and extracted relevant pages are retained through [the official-source retention index](issue-361-signing-diagnosis-v1/source_index/bb07c24a8c61a252f19b368aebead206f01a47eeb6e0dd04d4ccb33e1148c363.json.gz). It reconstructs the exact canonical source document `ccdbc7feae319a4d00367aebc84b7935e6155f0fad782491c39cbf085bb61965` from five ordered, digest-checked chunks; decoding that document's `content_base64` recovers the original PDF. Original PDF SHA-256: `a62baf6fdc5243fe79cbb582f7e61a359421524c27e3d47ae6eba78c6d5659fe`. Extraction used pypdf 6.14.2. These are engineering applicability sources, not threshold ground truth or an issuer-specific accounting adjudication.

The remaining work belongs to the Fundamental Service's source-specific identity, mapping, historical policy and release contracts: inspect original issuer/period disclosures; retain unresolved, missing and inapplicable roles; complete actual review; then publish trusted releases and invoke #352's composer. A signature cannot supply any of those missing inputs. The existing historical validation/conformance failures also remain, under #371. No valuation formula or policy was changed here.

## Exact evidence and repeat

[Diagnostic report](issue-361-signing-diagnosis-v1/report/c3a865e26c9dd2d741be6a19e7ec434edf321dd131a5d619f63d26c708597d16.json.gz) records exact commands, exits, runtime pins, signature subjects, source evidence and existing readiness digests. Input digest: `ecb9241d40b4956fcd5e5f9f136d80ea556c161bbcd2b9e09025e37a9492d6cb`. Output digest: `4cfb35083c609b4964c6c82d469071c3db4c02dfa76535aa84ded9a9847277fc`.

The complete diagnostic command ran twice at the same commit, including all 11 signer tests, both subject verifications, key reuse and the completed CI read. Both executions produced the same input/output/report digests. The second execution reused the source and report artifacts with `wrote=false`, unchanged bytes and mtimes. Test duration is explicitly normalized as `<elapsed>` in diagnostic command output; no replay statistics are normalized. The executor is retained alongside the report. This verifies signing and this diagnostic's idempotency, not full historical composer replay.

The first commit attempt failed the existing 500 KB added-file hook on the 813 KB compressed source document. Its canonical identity and diagnostic report remain unchanged: the retention index resolves that report's original source path through chunks, with an exact round-trip proof and each chunk below 250 KB. Rewriting the index also returns `wrote=false`. The hook was not bypassed.

[CI 42930923254](https://github.com/sosodennis/value-investment-agent/actions/runs/42930923254) completed on the observer commit with all 12 executed jobs passing. The legacy release gate was skipped and remains tracked by #372. The existing 556-service-test, separate 17-test PostgreSQL and 39 installed replay-test evidence remains bound to implementation `9a757bcd`; those suites were not represented as new executions here. The isolated service runtime tuple is unchanged.

Both models still have 0/100 canonical forecasts and zero paired independent issuers; errors and uncertainty are unmeasured, threshold evidence is underpowered, and `supported_history_threshold` remains null. Candidate mappings/policies remain provisional and unapproved; absent release-bound inputs abstain. PR #370 stays draft, #361/#369/#371/#372 stay open. Next acceptance step is original-disclosure adjudication and reviewed release-bound composer inputs, followed by full replay twice, review/CI, merge verification and issue-owned cleanup.

## Exact-head project seal repeat

Issue #361 checkpoint source: `32be2dafbbc7756bf185e228dc8fdcc280fe6cf3`. The repository's existing `fundamental-history-review-sign` CLI was used with the retained project identity `e541afcf1d21bb4afa58e56a6db3b222688c9ec89dfe590b54d9d11772556047`; no replacement signer or private key was created. Runtime pins: Python 3.11.15, Pydantic 2.14.2, and Fundamental Service lock SHA-256 `1f8a1bc3e6150f8d7bb3ba48778076bef51d72c3bbef7f020b1237998ed9a330`.

- Mapping proposal input `760ba098cdac8aa52b07bdb8e51a564adf7056ce13fb14d2b46eb0c84fd5011d`; seal output `239b35f08cc63a49e5a00b0b4e3374e61f1f5b1ee70bb6af8dd1090ddcabaa03`.
- Historical market-policy proposal input `97f2f7ddd4100cd990d3cb5197f3a8c94f46a349383ef535c7e4dfc60a88604b`; seal output `1b19eafd3af85026709252bfb10fb627df1e9621f6d46703ca5a8764a363b4a2`.
- Both initial seal commands exited 0 and wrote their artifacts (`wrote=true`); both `verify --subject` commands returned `verified=true`; repeating each seal exited 0 with the same digest and `wrote=false`. `init-key` also exited 0 with `key_wrote=false` and identity `wrote=false`.
- `uv run --project fundamental-service pytest -q fundamental-service/tests/test_history_review_signing.py`: `11 passed` (exit 0). The two output files decompress to their named SHA-256 digests and pin source commit `32be2daf`.

These artifacts authenticate the exact proposal bytes at this source commit and retain `review_status=unapproved`, `approval_granted=false`, and `independent_review_asserted=false`. They do not count as completed mapping review, policy approval, canonical releases, or composer execution. No forecast coverage or threshold result changes: both model forecasts remain 0/100 and `supported_history_threshold` remains null. Outstanding: independent issuer/period adjudication, policy approval, historical source validation, release-bound composer replay twice, and PR review/merge acceptance. Next: complete those owning-layer gates without substituting a project seal for a human independent review.
