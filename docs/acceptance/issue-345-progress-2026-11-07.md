# Issue #345 Acceptance Evidence

## Scope and exact commit

- Issue: #345, `Select a filing compatible with the pinned SEC validation runtime`
- Worktree: `/Users/denniswong/Desktop/Project/value-investment-agent-issue-345-filing-compatibility`
- Branch: `codex/issue-345-filing-compatibility`
- Base: `origin/main` at `08afd466`
- Head under test: `da1320c20106dcb0b456f339922c8b5771165e4c`
- PR: not opened yet; this checkpoint is the implementation and live-evidence handoff

The service runtime now binds SEC acquisition keys to both supported filing years
and supported filing forms. The verification deployment pins `2023,2024` and
`10-K`, so a producer request that allows `10-K` and `10-Q` can select the
latest filing that the installed validation runtime can actually validate. The
Compose service memory limit is pinned to a configurable 1 GiB default because
the isolated Arelle worker is a child process in the service cgroup.

## Checks on the exact head

| Check | Command/result |
| --- | --- |
| Focused compatibility tests | `uv --project fundamental-service run pytest fundamental-service/tests/test_source_acquisition.py -q` -> exit 0, `17 passed` |
| Fundamental service suite | `uv --project fundamental-service run pytest fundamental-service/tests -q` -> exit 0, `240 passed, 25 skipped, 1 warning` |
| Commit hooks | The `da1320c2` commit hooks passed trailing whitespace, end-of-file, YAML, large-file, Ruff, and Ruff-format checks. |
| Compose config | Two-file verification Compose config with the pinned resource paths and hashes -> exit 0. |
| Docker build | `docker compose ... up -d --build fundamental-service` -> exit 0; image `sha256:4c1bbea4fab2d5c60219cd111423c3b75aed8c5cf4570aa464e1ee7e7a5205d3`. |
| Docker health | PostgreSQL and Fundamental service healthy; service memory limit `1073741824`; `GET http://127.0.0.1:18696/readyz` -> HTTP 200 `{"status":"ready","contract_version":"internal.v1"}`. |

The live Compose project was
`value-investment-agent-issue-345-filing-compatibility`, using PostgreSQL host
port `18695` and Fundamental service host port `18696`. Its disposable
verification volume was retained; no reset or volume deletion was performed.

Pinned runtime evidence:

- `FUNDAMENTAL_SEC_SUPPORTED_FILING_YEARS=2023,2024`
- `FUNDAMENTAL_SEC_SUPPORTED_FILING_FORMS=10-K`
- taxonomy cache SHA-256: `0accc5ab0d4ce6674083bd82cf878a8619b3ac441da8600e0a03aefb8432a3a3`
- DQC ruleset SHA-256: `0eb33d095ac0ae08f01c508526b35523534659d661bc62873ac1400deec87930`
- validation profile digest: `639140b39584b3ee3276f09a011403dec911efe41ea1b98773f5f770bd5200d4`
- Arelle version: `2.47.4`; DQC ruleset: `v31.0.3`

## Signed live ingestion

Before the request, the disposable database was seeded through the existing
service-owned `PostgresMetadataStore.publish_mapping` API with the five
approved `sec-us-gaap-v1-*` mappings used by the producer. The PostgreSQL
volume was retained and the mapping payloads were immutable.

The producer-shaped signed request used CIK `0000789019`, ticker `MSFT`, the
five required fields (`revenue`, `operating_income`, `cash`, `debt`,
`diluted_shares`), no accession number, and forms `10-K`/`10-Q`.

- Correlation: `issue-345-default-msft-producer-20261107`
- HTTP result: `200`, `status=created`, `quality_status=verified`
- Selected filing: accession `0000950170-24-087843`, form `10-K`, filed
  `2024-07-30`
- Snapshot: `snapshot-19d11fc5a43fe4bebd3b03393edfedba`
- Manifest digest: `edad59d71ded9633c6d3373c2572d4b823d9c2530cb899e86b9416bd7a74d768`
- Canonical facts: `108`
- Parser finding codes: `EFM.5.02.05.14.hidden-fact-eligible-for-transform`,
  `EFM.6.05.42`, and `ixbrl:selfClosedTagWarning`; these are the known
  non-blocking diagnostics in the pinned replay.
- Runtime key payload included `supported_filing_years=[2023,2024]` and
  `supported_filing_forms=["10-K"]`.
- Source hashes: filing `4c2c360b4d2c20a773438b786956a0e8d62a8cd6ab8b3a3d4d5970bd283b6d0c`,
  archive `5a7653632f53c2529c4da82d25043fc52f05bfbe536837345aa5904560d92a82`,
  index `5692bbfccc76991d2cba6f4ddf2a8db9487dfce51ac5dded0b2607660a65a966`,
  submissions `1a4256a23be814a5193601a2c733d1da647c45da4d73dfe98eee58e32f8f9251`,
  and taxonomy member `0b71b0995cba38320a588bdeed7a516be06e1f681832ccb7f6d274bdb965d554`.

An identical signed request with correlation
`issue-345-default-msft-replay-20261107` returned HTTP 200 with
`status=reused`, `reused=true`, the same snapshot and manifest, and 108 fact
IDs. This proves the runtime pin is part of the idempotent acquisition key and
the replay does not create a second snapshot.

The explicit incompatible control used accession `0001193125-26-323660` (the
2026 MSFT 10-K) with the same pinned runtime. It returned HTTP 422 with
`FILING_RUNTIME_INCOMPATIBLE` and `retryable=false` before filing acquisition;
the audit row has empty source hashes and no snapshot or canonical facts were
published for that request.

After the live checks, the disposable database contained two successful
acquisition records, two snapshots, and 165 canonical facts (the one-field
2024 control plus the five-field producer request). The service remained
healthy throughout.

## Remaining gates and risks

- GitHub PR creation, exact-head CI, review, merge, and issue closure remain
  pending.
- #325 workspace desktop/mobile, keyboard, evidence-inspector, and
  same-snapshot valuation-trace acceptance must be rerun only after this
  blocker is merged into the #325 branch.
- The pinned deployment intentionally supports only `10-K` forms. A request
  constrained to a `10-Q` receives `FILING_RUNTIME_INCOMPATIBLE` rather than
  running an unvalidated parser path.
- The full service suite emitted one existing Pydantic serializer warning;
  no test failed.
