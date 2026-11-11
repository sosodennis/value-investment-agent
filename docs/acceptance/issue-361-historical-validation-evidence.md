# Current #361 checkpoint: fixed original inventory and observed byte differences

Implementation `4c65950b1d31797d0cb50a69d56674e586f3c3fc` extends validation to the unchanged100-issuer/589-filing inventory (541 original10-K,48 amendments,91 first original labels and9 retained missing labels). The installed-container setup regression is fixed by reading the frozen protocol/frame/snapshots from the explicit cohort root. Actual six original2016 source mismatches were proved to be exactly one terminal LF; a separate versioned integrity rule reconstructs the unchanged ZIP original and keeps every parser/DQC/release gate. [Rule and official XML basis](../../fundamental-service/docs/issue361-xml-terminal-lf.md). Two proof executions produced input `9e739066e2e8af64ce3ff5ddb274a26cedeccfb53844ae055695c223a1e55bcf`, output `597b47d83e523c4caf5cc6152f06a2bfe1cbefc974ef4c27c30bb813d3edc09d` and second wrote=false.

Exact implementation checks:495 service tests passed/26 skipped,17 PostgreSQL tests,20 acceptance-tool tests;25 changed service source files plus the batch script and four tooling files pass pinned mypy. Ruff/format/Bash/architecture/contracts/preparation-parity/diff pass. Exact Docker preflight passed for image `sha256:303673a4d4ae36812aa89c78d4a08c8cb18cfb24b3cb1fe63f4df1066cf3a132` matching54 source files. Source pins are unchanged within each execution.

Docker's virtual disk filled during the earlier0b51372a batch after14 observations; this infrastructure failure was not classified as financial absence. A SHA-256-verified copy of197 evidence files relocated this batch's source storage to the issue-owned ignored host directory; the same-path bind and /tmp bind are recorded in the new Compose tuple and preflight. Seven untagged unused images explicitly identified by #361 evidence were removed without force; no shared cache, unrelated image, container, network or volume was removed. The earlier run resumed14 unchanged observations and later retained54 total before an explicit controller interrupt to apply the observed byte correction. Those54 outcomes, setup/space/interruption failures, scripts and commands are preserved; they are not a complete589 run.

The exact4c65950b589 diagnostic run is currently in progress. Full repeat, reviewed historical identity/mappings/policies/releases and #352 composer replay remain incomplete. Both thresholds remain null; PR370 is draft, and361/369/371 remain OPEN. Project seals verify and reuse the retained private key, without asserting independent review.

Progress evidence: [report](issue-361-fixed-original-validation-v1/progress/1b34c81f80114698db3694a34f128a12eda0cce97478b8b20252b5fc44fafa62.json.gz), input `5d958ef2ec8696702267ce88427807dcf203fdaf480a6385b0cdb8860dc14799`, output `1242ae74c1cf9e1c8200dbf079b199d1014a8e5c216de1427ee064da14c2262e`. [Canonical runtime tuple](issue-361-runtime.json) remains BLOCKED. No full fixed-cohort replay acceptance is asserted.

# Current #361 checkpoint: service acceptance tooling

Implementation `bca30f42c266c93744ddbb6c3f7d38a67c0ec724` adds explicit Fundamental-only acceptance, and #361 now runs through required contract-policy. The [canonical runtime tuple](issue-361-runtime.json) is BLOCKED. The earlier service diagnostic tuple is preserved as historical evidence; its schema rejection is no longer the current tooling limitation. #351–#355 app/browser contracts and acceptance artifacts were not changed.

Exact-commit checks passed: 476 configured service tests/26 skipped, 17 isolated PostgreSQL tests, 20 acceptance-tool tests, 24 changed service source files plus four tooling source files under pinned nonincremental mypy, Ruff/format/Bash syntax/architecture/contracts/parity/diff. Whole-module type cleanliness is not asserted. The initial real preflight stopped because the new gate assumed loopback while the existing project publishes on 0.0.0.0; the tuple now pins the actual host binding.

Actual Docker preflight twice produced input `72fec235aeb8b33eeb2a94595c1ffc552eac13c429b97e0bdfe80704ad38e44d` and output `6c50270f0647e994112fa5cdd14d08bdd8826a00d83869c20b8455a32f1220fe`. Repeats reused report `ce0971320bd64cf5bb598fd55271053d61190c853ae55cbe2cfefd7bcba47145` with wrote=false, zero new files and unchanged mtimes. This checks source/image/env/config/health/ports/resources/runtime/readiness, not historical forecasting. Aggregate input `e4f46adcee99f25888550b6b057ebb773f350c3dee190d8db1248c7f6d2fb718`, output `c6258579a8736de54dbace0dd2d2d03ed269834224a3c851684df80c96bf944a`, [report](issue-361-service-acceptance-v1/report/227825589d2b41e572c10f44d193a8569a3e0dec31f85efbb541d217d1d2f103.json.gz) retain exact commands/results, runtime tuple and executors. Report publication also repeated with wrote=false.

Full fixed100 original validation, approved issuer/period mapping and historical policies, actual composer replay twice, and full acquisition execute audit behavior remain unresolved. No independent review or complete replay acceptance is asserted. Both thresholds stay null; PR370 stays draft; #361/#369/#371 stay open. Next: complete historical source/identity coverage and actual review before release-bound replay.

# Historical validation evidence for #361

Status: **PARTIAL_NOT_REPLAY_ACCEPTANCE**. #361, #369 and #371 remain open; PR #370 remains draft. Both supported history thresholds remain null. The unchanged fixed cohort still requires independently reviewed issuer/period mappings, approved historical policy inputs, canonical releases and actual composer replay.

## Current original-identity checkpoint

Exact implementation `531c9e76ffb2b00f1d1a902af883af658db5b5dd` adds the explicit `original-filing-dei-v1` identity policy. Historical acquisition checks the pinned CIK without present-day ticker membership; before publication the service requires matching original DEI issuer/security facts, real namespaces, unambiguous contexts/report period and consolidated reporting currency. Missing/conflicting/security-dimensional evidence is retained as refusal. Contemporary identity checks remain the default. [Contract and official SEC applicability research](../../fundamental-service/docs/issue361-historical-identity.md) explain why this policy does not establish complete 2016 identity coverage: cover-page tagging was phased in from 2019 through 2021. A validated original cover-page/class policy remains outstanding.

Exact final gates pass: **476 configured tests / 26 skips**, **17 PostgreSQL tests**, all **24 changed source files** under pinned nonincremental mypy, all **44 changed Python formats**, Ruff, architecture guard, contract generation, four preparation-output parity comparisons and diff checks. Existing project proposal seals verify; key initialization reuses the existing private key. Broader unmodified module types are not claimed clean. The live OpenAPI exposes both identity fields and the existing default. New identity matching/refusal is tested through synthetic owner/service/source-header seams; no fixed-2016 issuer security identity is asserted.

The actual original SEC sample again runs twice in isolated Docker/PostgreSQL. Input `64de61ab86c1ac19b8b18f531fd1d591d4340c7bd69ffedb7dc671d3b2241374`; output `0c7a0a1b211ede9dcaebce27a7705c4f9ff0dc49fbeb6b20c6c87ac3aebd6fb4`. Second execution: zero original reads/downloads/new files or rows across the six checked evidence/publication tables, unchanged existing mtimes, `wrote=false`. Original `DQC.US.0015.2098` blocks publication before identity matching; all 327 facts remain accounted for. This is a source-validation diagnostic, not full acquisition/replay acceptance. Full `execute()` operational audit idempotency is not established.

Canonical [report](issue-361-historical-identity-v1/report/a516f9dbc25cd02f349311328d294f4d65ea723b0d7bb9c83b641add5177587e.json.gz): `a516f9dbc25cd02f349311328d294f4d65ea723b0d7bb9c83b641add5177587e`; verification `12b09ecb704af48a514966244bebef829ee70dea6f05a3bdbdeb0aa75e971bd6`. The report retains exact source/runtime/input/output/commands, both executions, prior `6b79a2bb` checkpoint checks, the strict-tuple fixture failures and correction, scripts, signature verification and the conservative currency refinement. Canonical report publication itself repeats with `wrote=false`. Image `sha256:2322874f77b35f970e18b59faea9517a1f0328a8a3e77bd221c6795e0be3696f` matches all53 Python files at the final implementation; [runtime](issue-361-service-runtime.json) records the same healthy isolated project/ports/env and asset pins.

The generic application/browser acceptance-manifest validator rejects the service-only tuple (exit1); `contract-policy` currently does not gate361. [Retained tooling diagnostic](issue-361-historical-identity-v1/tooling_diagnostic/d33ef09f4e97b5b1e9f7b838415c1370d14afa8c2c23072cdc37835a0ec56d1e.json.gz) records exact source/command/manifest hashes, input013192095b2eb95a1a6573788b2f95627994f7a5b8918ca7c686f37e5baec3b3 and output1abd5f65a145ce5d09a631200454577ca23398e2d93860c346d946958c42b6a5. The tuple is direct service diagnostic evidence, not a passing standardized acceptance manifest. #371 records the need for an explicit service-only scope in owning manifest/preflight/policy tooling; no app/browser identity is fabricated.

Both thresholds stay null. Full100 original validation, original historical security evidence, independent mapping/policy approval, release-bound actual composer replay, service-only acceptance tooling, review/CI, merge verification and owned cleanup remain incomplete. Earlier checkpoints below retain their original exact-commit status.

## Earlier source-retention checkpoint

Exact implementation `e73c58051653a0e227364bde3c8e358862c8f422` fixes the remaining changed-file type gates and adds durable original SEC response receipts to production pinned-accession acquisition. All **23 changed source files** pass mypy 1.19.1 with `--no-incremental`; **449 configured tests pass / 26 skip**, **17 PostgreSQL tests pass**, and all **42 changed Python files** pass formatting. Ruff, architecture guard, contract generation, preparation-output parity and diff checks pass. The broader unmodified module type baseline is not represented as clean.

The actual original sample runs twice through the retained service source adapter, PostgreSQL content/artifact stores and strict historical ingestion in isolated Docker. The second run reads/downloads zero original responses, creates zero files and zero rows across six evidence/publication tables, preserves all existing file mtimes and returns `wrote=false`. Input `9ecc34cadc6586867479317a834fe6b428e7169334b0833d7b4a80305a088ef0`; output `4e2c6466fafc5969c7c2f7d8d0c067222cf283845c529238e8e45334546d1be3`; report `ccf481a3f7bae122e9ec0f430b04c33e7324aeedddd75c312c9cfd419cd601fe`. Canonical documents, exact commands, executors, observations, proposal-signature verification and source hashes are under `issue-361-service-retention-v1/`.

Image `sha256:208308938ab7426fdef8fe272ce487099ff0e5730458959804d0453b617a88e3` matches all **53** source files at this commit; the service/database remain healthy on the same isolated project and ports. Original blocking `DQC.US.0015.2098` and 327 extracted facts remain retained; no canonical snapshot/release is published. Four complete original response receipts remain in the earlier evidence below. Valid FCFF/transition preparation outputs match the prior checkpoint byte-for-byte in four policy/model comparisons.

The retained source key is CIK/accession/valuation timestamp/source-selection policy/URI. It is independent of model/mapping/validation revisions, uses the existing stores and serializes provider capture with PostgreSQL advisory locks. No request state mutates the shared ingestion adapter. Corrupt evidence fails closed. See [retention contract](../../fundamental-service/docs/issue361-sec-response-retention.md).

A separate historical identity gap is now recorded in #371: `_decode_submissions` still gates formal historical requests using the current SEC ticker list. That check has not been bypassed. Full fixed-cohort source validation, historical identity, independent mapping review, policy approval and actual composer replay remain open. The earlier type-failure counts below describe their exact older commits, not this checkpoint.

## Official suite conformance

Exact execution source: `445dc6a83c92a96c01ca9d87a2ffbf378fb6bafb`. The production historical adapter executed all 2,349 declared official DQC v1 variations in four fixed modulo shards. Every case matched expected rule codes, counts and original severity; all six official modules completed. Network attempts and failures were zero. A second complete execution reproduced every input/case/shard digest, wrote zero new case artifacts and returned `wrote=false` for input and reports. This certifies the tested official suite only, not the fixed issuer cohort or later taxonomy namespaces.

| Artifact | Canonical digest |
| --- | --- |
| Input | `fadfbe4b09f5651759e433727a8efcfbe0cddb724f3f440d933fc56186f1e727` |
| Semantic output | `9196919698b2b3bc5868b0902883d4eb5980ed0c7e048c1d148754b23aed281e` |
| All per-case findings | `fd4acf1547450a7cc86e3d44755da9cf65c54820c93f41089e4bec4b2b692802` |
| Official assets and original external receipts | `9f1744eb8664e0f3019ce23896555ff83abcd756d5d5a134a530884827de103a` |
| Checks, executors and raw observations | `9b4cb6fbf410dc8352194fe8a7d85d5f1a8378ade81cd6bfe3e2d0b7e32b1ac0` |
| Report | `7d791b50b58a9021063d455317992ba29ca1e86e03fa9781b26d45842e61b13e` |

Artifacts are under `issue-361-historical-conformance-v1/`. The report contains ordered case references, all findings, four exact commands and exit codes, both execution observations, original scripts and immutable source/cache/runtime identities. Official suite ZIP SHA-256: `df30183a1315ba1323b873aea572a2c068b8c5e70d4939c5d824f1cdedd6994f`. Three externally referenced original SEC ZIPs and six additional original taxonomy files retain their receipts. The initial 2,346/2,349 attempt incorrectly treated those external URLs as local paths; its failures and executor remain retained at digest `64fdcd17e3e795ae11864c202fc832b5c2190c27fcf3b6992cb2e056ce9e18d3`.

Literal coverage remains US GAAP 2012–2015 and DEI 2009, 2011–2014. Unsupported/mixed namespaces, changed official package bytes and partial module execution fail closed. The original rule severity survives EDGAR's warning releveling. No official rule or valuation formula was rewritten.

## Original SEC acquisition and retained rejection

Exact source: `5775380b5c8ca35112f1ea3441be9694ae182d79`. CIK `0001539778`, accession `0001477932-16-007985`, decision `2016-01-12T19:35:54Z` were unchanged. Captured submissions confirm non-inline XBRL and exactly match the fixed acceptance timestamp. Current ticker/survival fields are not used. The service chooses indexed original `acug-20150930.xml` from the standalone instance/schema pair and retains ambiguity/missing failures.

The original direct XML is LF, 249778 bytes, SHA-256 `b7fb0c0fe68f7d0d8353940d486801dc439509853453c68ca55405fbf50b3d55`. The original accession ZIP is 45119 bytes, SHA-256 `3c5bc3e9b3987c81b16863286843cc37ea3ef38ba7b5dfedb26d876a49c3523d`. Its member is CRLF, 250838 bytes, SHA-256 `fc13b856abb859aab0c3e23deb20c1801054d9742ee7f7c8f1acf92c9e7040d1`. The versioned XML 1.0 rule proves the sole 1060-CR representation difference and reconstructs exact archive bytes. Original bytes, response metadata, index, archive, normalized/parser hashes and rule digest remain traceable. See the [owning validation contract](../../fundamental-service/docs/issue361-historical-validation.md).

Actual ingestion completes strict EFM and all six historical DQC modules, extracts 327 facts and retains blocking `DQC.US.0015.2098` with original error severity. It publishes an immutable rejection and zero snapshots/releases. Diagnostic security identity is explicitly excluded from canonical publication. This is a verified source-validation rejection, not a verified valuation or forecast.

| Runtime | Input digest | Output digest |
| --- | --- | --- |
| Host | `54671be495a007a185bbbbcb33bd749ad429253a856c74601ed10f65deaac42e` | `268b58eb7465858abcb4a4739a655c588305d3c258b353ac4b030357296a647e` |
| Isolated Docker | `5f1248c66b83f436cb24d778e2809a80552ff52856823bc798f88d43d274e6b2` | `ae78f9647a985cce48deed35f2f88c3a69d62d944764b6f918ed7b15c7860f48` |

Each runtime executed twice. Its second run reused identical inputs, outputs and rejection identity, with zero downloads/new files and unchanged existing mtimes. Host and Docker pins differ, so their digests are separate. The Docker executor refuses missing original captures. Stable capture keys bind CIK/accession/valuation timestamp/source profile/URI; no run ID or current clock identifies data.

The four complete original response receipts are canonical source document `bf9e5813b9875c7ccdc87d5e6faaccabebac206a0f66ffd96ef5b231adc1273b`. Verification document `324943cefad2d4cd41b2752324bdf8f054e58c3e3437412639a900c2bc57488f` retains all originals, scripts, exact commands, tests, runtime, signatures and failed setup attempts. Aggregate input/output: `5f4404ca5493b13d1cf90ef7a084bfcd027807749d00ab69258cee7a29d826ec` / `e58c439a975d4dd262f3302643839665b588b7603fa3d32b35db2e99991b9a73`. Report: `7febca2a119640579ccc37ff75d730740c96967b9967fd9176523121cc421539`, under `issue-361-original-acquisition-v1/`. Both reports use the existing canonical temporary-file/atomic-rename writer and their second publication returned `wrote=false`.

## Exact source checks and remaining acceptance

On `5775380b5c8ca35112f1ea3441be9694ae182d79`, configured service tests passed **434**, with **26 skipped**; isolated PostgreSQL tests passed **17**. Six source files covering parser, acquisition, facts, contracts, integrity and ingestion pass pinned mypy 1.19.1. Ruff, 38 changed Python formats, architecture guard, contract generation and `git diff --check` pass. Current checks artifact: `df54bbbda7f737d2b5026c993876261463a5a67c5bf0200d9a799d1c2ba9803c`. Both project proposal signatures verify; persistent key initialization returns `key_wrote=false` and reuses its public identity. These remain unapproved proposal seals.

Full type acceptance still fails: mypy 1.19.1 reports 11 errors in policies, 93 in valuation preparation and 9 in application/service. Counts from older mypy runs are not reused. CI run `42819531188` passed all 11 executed jobs; the Fundamental release gate was skipped. It does not establish release acceptance. The earlier configuration-index failure and its minimal fix are retained.

The [runtime tuple](issue-361-service-runtime.json) records image `sha256:913f7a9565e8132381c1d9c0b9d32cad18c04ba45211642e73c7e79f86f316d2`, all 52 matching source hashes, healthy service/database, readiness with identity resolution configured, the three ordered Compose files and both env-file digests. Project/ports remain `value-investment-agent-361-replay-evidence` / 18661 and 18662. No other project resource was changed.

Next: complete remaining type gates, extend original-source validation to the unchanged cohort with every failure retained, complete independent accounting review and historical policy approval, and execute the actual release-bound composer replay twice. Report forecast error, coverage, independent issuers, uncertainty and missing labels before deciding whether evidence supports a versioned threshold. Underpowered results keep the threshold null and valuations provisional or abstained. Merge, closure and cleanup remain pending.

## Read canonical evidence

The report's artifact descriptors use either direct canonical JSON gzip or fixed 256 KiB chunks. This reader verifies each digest and reconstructs exact original canonical bytes without creating a large tracked file:

```python
import base64, gzip, hashlib, json
from pathlib import Path

def read(root: Path, descriptor: dict) -> dict:
    def checked(path: str, digest: str) -> bytes:
        raw = gzip.decompress((root / path).read_bytes())
        assert hashlib.sha256(raw).hexdigest() == digest
        return raw
    if descriptor["storage"] == "canonical-json-gzip":
        raw = checked(descriptor["path"], descriptor["digest"])
    else:
        pieces = []
        for item in descriptor["chunks"]:
            chunk = json.loads(checked(item["path"], item["digest"]))
            part = base64.b64decode(chunk["content_base64"], validate=True)
            assert hashlib.sha256(part).hexdigest() == chunk["content_sha256"]
            assert len(part) == chunk["bytes"]
            pieces.append(part)
        raw = b"".join(pieces)
    assert hashlib.sha256(raw).hexdigest() == descriptor["digest"]
    return json.loads(raw)
```
