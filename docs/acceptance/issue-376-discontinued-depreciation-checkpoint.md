# NEWMARKET discontinued D&A evidence (#376, #381)

Implementation: `ecb09fa8fec47dffc762ce51fb4dd951468c17dd` on
`codex/issue-376-discontinued-depreciation`, based on #399 at
`4fb5e85ec10c2a93c9be1f80cf6bf0838f838448`. Earlier checkpoints remain intact.
The Fundamental accounting evaluator now represents one original discontinued
D&A exclusion against its aligned consolidated duration base. This changes no
forecast formula, semantic approval, trusted release or history threshold.

At the exact implementation commit, 864 Fundamental tests pass and 48 explicit
database/resource checks skip. This includes 35 new boundary cases. Ruff 0.14.10
check/format, mypy 1.19.1, both architecture guards and `git diff --check` pass.
The external verification receipt records every command, exit code, normalized
output, file/runtime pin, input digest and output digest. Pytest elapsed seconds
are excluded from result identity; outcomes and counts remain intact.

Two real originals, `0001282637-15-000004` and `0001282637-16-000028`, freshly
parse offline with unchanged complete parser/fact digests. Both retain the 2013
consolidated D&A observation 46.144m and the explicitly discontinued 5m
observation at `decimals=-6`. The nominal accounting relation is 41.144m; it is
not an unrounded continuing-business truth. The original dimensional fact,
precision and classification passage survive ingestion and canonical decode.
`AllOther` 4.683m is not substituted. Both mappings and facts remain provisional,
unapproved and unpublished.

Two additional complete fresh-process relation replays exit 0 with identical
stdout/input/output/report digests and `wrote=false`. There are zero new source
or relation artifacts/downloads, and 1,213 existing source/cache files retain
their bytes, sizes and mtimes. This is not the complete forecast replay.

All generated evidence and executors remain under the existing external
`value-investment-agent-issue-376-research-evidence` root, outside Git:

| Receipt | Report digest | Input digest | Output digest |
| --- | --- | --- | --- |
| `checkpoint-ecb09fa8/discontinued-verification` | `4bc051dcf11f2e7b7c8b28c7ec7bbc9c728fa95a25ead2c1902c08a13f5129e1` | `c39bc4be12549527e826d17b689e083de816fe55ba245046de328ca6252d77dd` | `c779908fc9523f62a0c74381ad2fe4d531bef258ee67532aff8fa5c0dd800f97` |
| `checkpoint-ecb09fa8/discontinued-depreciation` | `5e13678b3e0d214a70b4892532ee47b9b48985e49290ed190d4c2bb48099ef46` | `0a089ede873350d6224008b404d3660eec49406f5949426d24e08d7c8d5a1ed9` | `614b2f6aad3dbd43dbcaeb8c60f6c3e4d7209b6de3bb8b5e02cccee9b87414f9` |
| `checkpoint-ecb09fa8/discontinued-repeat` | `176b0cc06da9f7847a36b4dfda9cc7f0ea175156592aa0beb2216362aeba0f79` | `69c2ed353989d78d755794f13ca3cd07458fa6693528361cf19ed123006cdabb` | `a00b51bfd30540cd892c428506a3e016c9db60cb96becac030efb065d476e357` |

Reproduce at the clean implementation commit with the locked Fundamental
runtime. Each external executor takes the exact commit SHA as its final argument:

```sh
uv run --frozen --project fundamental-service python <evidence-root>/references/issue376-discontinued-verification.py ecb09fa8fec47dffc762ce51fb4dd951468c17dd
uv run --frozen --project fundamental-service python <evidence-root>/references/issue376-newmarket-discontinued-depreciation.py ecb09fa8fec47dffc762ce51fb4dd951468c17dd
uv run --frozen --project fundamental-service python <evidence-root>/references/issue376-discontinued-repeat.py ecb09fa8fec47dffc762ce51fb4dd951468c17dd
```

Remaining: independent semantic review of rounded/complete continuing D&A and
capex; the four receivable/accrual/contract-asset/deferred-revenue roles; actual
trusted releases; both formal forecasts and first-original labels/errors;
reviewed #377; isolated service-backed acceptance; PR review/CI, integration
and merge-SHA verification. Complete study cases remain **0/100** and
`supported_history_threshold=null`. No parent checkout, database, Docker or
signing configuration was changed. Keep #376/#381 open and this increment draft.
