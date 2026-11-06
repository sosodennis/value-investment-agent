# Issue #328 SEC Artifact Integrity Evidence

Issue: [#328](https://github.com/sosodennis/value-investment-agent/issues/328)
Branch: `codex/issue-328-sec-integrity`
Base: `main` at `bee63cb37da9edb2deb444e14d2fc666aed73d06`

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
| SEC accession index JSON | 200 | not returned | 10,170 | `556272b4254475f458cdf6395db66c5aaee90d0a0618dc429767bfe96a75bace` |
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

## Parser and Publication Checkpoint

Status: partial verification only. This checkpoint does not mark #328
`VERIFIED`; Docker health and the end-to-end service acceptance remain open.

The SEC runtime pins used for the offline parser replay were:

| Artifact | Version or SHA-256 |
| --- | --- |
| Arelle | `2.47.4` |
| SEC EDGAR plugin | commit `4891c4c9889c77af247428ceff4fa7cc52d534ea`, tree SHA-256 `63e4b5540a6754a1d6ad86a34ec1aa70f3f7da90e46c6fa3959686d8b2ac7330` |
| SEC EFM | release `26.3`, validation plugin `1.26.3` |
| Xule | version `30055`, commit `7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc`, tree SHA-256 `e32ff88b52df8bf1e6aca3e63edabbc0b2f3513b7d0627ca9163db00d2a5678b` |
| DQC US | `v31.0.3`, 2024 ruleset SHA-256 `0eb33d095ac0ae08f01c508526b35523534659d661bc62873ac1400deec87930` |
| Taxonomy cache | SEC public 2023/2024 bundle SHA-256 `0accc5ab0d4ce6674083bd82cf878a8619b3ac441da8600e0a03aefb8432a3a3` |
| Validation profile | SHA-256 `16ba86548ada480dbb35c94216a7512bab944ba25207f1ef048f296a593474e2` |

The locked service runtime now includes the SEC EDGAR plugin dependencies
`aniso8601` 10.0.1, `holidays` 0.108, and `pytz` 2026.6. Without these
dependencies the pinned plugin could not load in a clean service environment.
The successful Microsoft replay uses the filing-referenced 2023/2024 taxonomy
bundle; a 2024-only cache left DQCRT with no rules and is not acceptance input.

| Check | Result |
| --- | --- |
| `uv lock --check` in `fundamental-service` | exit 0 |
| `uvx --from ruff ruff format --check` on the four changed parser/test files | exit 0 |
| `uvx --from ruff ruff check --select E,F,I --ignore E501` on the four changed parser/test files | exit 0 |
| `git diff --check` | exit 0 |
| Focused parser, integrity, ingestion, rebuild, source, and snapshot tests | `31 passed, 2 skipped`; the two runtime-gated tests were run separately below |
| AAPL SEC EFM/DQC replay, twice with the pinned offline runtime | exit 0, `1 passed`; 1,127+ facts, blocking `EFM.5.02.05.disallowedElement`, identical replay digests, zero network attempts |
| Microsoft SEC EFM/DQC replay, twice with the pinned offline runtime | exit 0, `1 passed`; 1,856+ facts, no blocking findings, identical replay digests, zero network attempts |
| Ingestion regression test | included in focused suite; normalized bytes must be semantically identical, raw bytes remain retrievable, and blocking/mismatch paths publish no snapshot |

The fixtures are identified by AAPL direct response SHA-256
`a14d584e9804a87e92ddbd2446ade975e926a494671292403c811c1f4fc4b846` and
Microsoft test ZIP SHA-256
`9315745e8b66735afd8be0f63a2d5876d350eb7ae7be80a7e0aff015df76acf0`.
The live SEC response and archive hashes above separately establish that the
script is absent from the canonical accession ZIP member.

Exact replay command:

```sh
ISSUE328_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
ISSUE328_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
ISSUE328_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
ISSUE328_TAXONOMY_CACHE_DIR=/tmp/issue312-sec-taxonomy-2023-2024 \
fundamental-service/.venv/bin/pytest -q \
  fundamental-service/tests/test_arelle_parser.py::test_aapl_sec_efm_dqc_replay_records_blocking_finding_and_zero_network \
  fundamental-service/tests/test_arelle_parser.py::test_microsoft_sec_efm_dqc_replay_allows_verified_fixture
```

Docker health, real service-backed snapshot publication from the clean filing,
and exact-commit acceptance remain pending. Publication remains fail-closed
until those gates are complete.
