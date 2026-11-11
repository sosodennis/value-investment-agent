# Issue 361 combined XML source proof

Implementation `d52787c301bff0e6af45beae6c497b8fb4dfceb1` adds an independently versioned, accession/size/hash-bound integrity rule for the observed combination of CRLF-to-LF and exactly one final LF. The unchanged ZIP member remains parser input. No valuation formula, policy value, mapping approval, quality status or threshold changes.

The complete frozen4c original diagnostic remains in [its report](issue-361-complete-original-diagnostic.md). Of its210 source-size refusals, exactly23 satisfy the new byte relation and187 still fail with their identical prior error code/message. This comparison uses the same retained raw/index/ZIP receipts; it performs no provider request, mutates no source and publishes no canonical snapshot/release. Byte equivalence is not regulatory or financial validation.

## Exact source checks

[Command ledger](issue-361-combined-xml-proof-v1/checks/c45053deb1cff08c430495d4a1c482184ea0bcc3af9c0ff91ed9750f6087937c.json.gz) retains all13 command exit codes, stdout, input/output digests and source SHA. All exited0:

- Service suite527 passed/9 optional skipped;17 PostgreSQL tests are included in527 and also passed separately against this issue's separate `issue361_ci_contract` database.
- All28 changed source/script files pass pinned mypy1.19.1 with real service dependencies and shared contract types. This is changed-file evidence, not a whole-service type claim; the retained executor descriptor records that scope.
- Ruff0.14.10, all50 changed Python formats, architecture guard, generated contracts, preparation parity and `git diff --check` pass. Policy/model canonical parity remains `e33ea7474f604c514be4d0236d9594fbf163b53b54525f89e9733b200490b8d5`.
- 20 acceptance-tool tests, tooling types/lint and Bash syntax pass.

[Regression receipt](issue-361-combined-xml-proof-v1/regression/b344173c98c031d1b7f703d967590399b8da38da97eb02c7a982279a50d3ef93.json.gz) preserves the positive case failing before the fix (`SOURCE_ARCHIVE_SIZE_MISMATCH`,1 failed/7 passed) and all43 integrity tests passing after it. Negative cases retain value/text changes, extra newlines/spaces, incorrect sizes, unsupported version/namespace/media and DTD refusals.

[GitHub CI](https://github.com/sosodennis/value-investment-agent/actions/runs/42860942298) matches the exact implementation and passes all12 executed jobs. The manual legacy release job is skipped; its prior input failures remain tracked in #372. [Retained CI identity](issue-361-combined-xml-proof-v1/ci/a4be566a573d4c43c416f2566e5c58282dc93555d651374ac4c60a24337b5402.json.gz) records individual jobs.

## Original-receipt proof and repeat

The [210-case proof](issue-361-combined-xml-proof-v1/proof/ee357d40bc6221f8e5afda0655156c05850c971e99f9fd98432844ff5d13d6c0.json.gz) binds the exact prior/current source, original result digests, source hashes and per-case rule signatures. Input digest `f1c0f013497d878ad16048100f1d5a81ce0ac1d43ffdf1807de57cb6f91a5e33`; output digest `787f2b46a81fb99e54cdd213c5cbea1f302ae81de785b7660f15ad0594737288`.

```sh
uv run --frozen --project fundamental-service python /tmp/issue361-combined-integrity-proof.py
```

Both executions exit0. The [complete executor source](issue-361-combined-xml-proof-v1/executor/08bc0e4eb785240e2f35401b9cef32b08bf7db7234cac71020ccaec400b0c0ba.json.gz) is retained. The [second execution receipt](issue-361-combined-xml-proof-v1/repeat/441eb5e020964229c42455578e1805c16c5fba7f92d68698a723d8d2173327d5.json.gz) confirms identical input/output/proof digest, both artifacts wrote=false,zero new files and unchanged bytes/mtimes. This is not full composer replay acceptance.

## Docker and official compatibility research

The isolated candidate project `value-investment-agent-361-candidate-contracts` uses ports18663/18664 and its own network/volumes. Image `sha256:326890cf718a76b5b6c8af0b8a1a6e2dcdc2f92a2b05e8377aed286e64e465b8` matches all54 exact source files and is healthy. Its additional original-evidence bind is read-only. [Build](issue-361-combined-xml-proof-v1/build/e1ccfb123aa3f26d5d67dec4bae2d9248c4ef186a0bb8d921b58b81787b11d45.json.gz) and [startup](issue-361-combined-xml-proof-v1/runtime_start/1be5b944af0c6239ba52477b10a337fc8f1c6e8d5ba918ebb1806cd8999e1409.json.gz) retain exact commands/exits. Initial service preflight correctly refused uncommitted evidence;after metadata checkpoint `fe6bbd122cd51811fd19d20b26fdc027817227e0`,both clean executions exited0 with identical input/output and second wrote=false.

[Runtime verification](issue-361-combined-xml-proof-v1/runtime_verification/157a36677c50460d2210faacd4e7907fc67b4dbd05441c98210211f2be5dca04.json.gz) records source/observer commits,commands/exits,initial copy-permission failure and its ownership correction,project signature verification and key/identity wrote=false reuse. Verification input `550a6c93310a51fa70c2c44d3c447a899ee19bc787e8614a753c61b2f1823099`;output `e88d4360e29e7f9f872871e9ccfd0199ad229581f1970b7fb96f2120c7e1f0ab`.

Actual [service preflight](issue-361-combined-xml-proof-v1/service_preflight/ed2c6fef1414ae5f1989b71cc744f2e661daa539d5e3030552736ffee98860f0.json.gz) twice produces input `8c118ca32148595998c6b0d68236232d9195aa354e1823a4bcf3310f866989ae` and output `cc12396c12ffe3c9cefd7434a3f16f88e8e748b6bcf5d86f0c1890ce4e238a0c`;the second reuses its report. The installed-container proof also repeats identically,input `1bf441e68af18c7f277aaa7dcc4ce653f595470c618b4acb3858fae5f7799a09`,output `16ce6292baa5e17369093349da765aaacd8c68b1c6f47853dd504a5721facc02`. It verifies all210 prior failures against the read-only original-evidence bind,exactly23 proved/187 refused,with every accepted rule signature matching the host proof. It calls no provider,parser,composer or publication API.

The [canonical runtime tuple](issue-361-runtime.json) remains BLOCKED. The [archived4c tuple](issue-361-original-runtime.json) describes the completed diagnostic. The same owned original project now has a separately pinned [EA diagnostic](issue-361-latest-original-runtime.json) in progress with retained raw receipts; its partial results are not a complete latest-source or composer replay.

[Official DQC research](issue-361-combined-xml-proof-v1/official_research/c2645e033d5e9cfabe0eece60b6232f9457d42d7f2a243f96726bfe703f1d161.json.gz) retains GitHub command, immutable source URL/hash/bytes and findings. The fixed v1 profile's113 unsupported filings comprise58 US GAAP2011,54 GAAP2016 and one GAAP2018. Official v3.6.2 source `cafb54391c1d21e4c219bc3d491b855a9b877cb6` declares2016/2017, unlike v1. It has not been installed or certified here. Its full rules/resources, offline schemas, all-hook completion and official conformance need separate verification; changing year declarations alone cannot establish support. The2011/2018 failures remain in the denominator. This research supplies no financial or threshold ground truth.

## Remaining acceptance

The user-requested [project signing CLI](../../fundamental-service/docs/issue361-project-signing.md) exists, reuses its retained private identity and explicitly seals proposals as unapproved. A signature cannot substitute for an actual independent issuer/period mapping or historical-policy review.

Both models remain underpowered: no canonical paired issuer predictions, null error/uncertainty and `supported_history_threshold=null`. Affected valuations stay provisional or abstained. Remaining work is actual historical validation/identity, reviewed mappings/policies, trusted releases, full #352 composer replay twice, review/CI and merge-commit verification. PR370 stays draft;361/369/371/372 stay OPEN. No #351–#355 acceptance or unrelated resources were changed.
