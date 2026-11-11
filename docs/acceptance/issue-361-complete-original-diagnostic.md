# Issue 361 complete original-source diagnostic

The fixed 100-issuer/589-filing diagnostic completed on implementation commit `4c65950b1d31797d0cb50a69d56674e586f3c3fc`, image `sha256:303673a4d4ae36812aa89c78d4a08c8cb18cfb24b3cb1fe63f4df1066cf3a132`. Evidence was retained and rechecked at observer commit `89f125bd74b04f0666d64a1244d92ceb2ec639e5`. This is source-validation coverage evidence; it executed **zero composer forecasts** and grants no mapping, market-policy, security-identity or release approval.

| Frozen role | Passed, unpublished | Refused | Total |
| --- | ---: | ---: | ---: |
| History | 29 | 369 | 398 |
| Decision | 3 | 97 | 100 |
| First subsequent original annual label | 0 | 91 | 91 |
| Total | 32 | 557 | 589 |

All 100 issuers remain in the denominator. Nine issuers have no first subsequent original annual filing in the fixed source inventory. CIK `0001137091` retains its first original label `0001137091-19-000016`, but the 731-day period gap does not match a one-year forecast horizon; no later or replacement label was substituted. The three passing decision instances lack `TradingSymbol` and `Security12bTitle`; their diagnostic identity cannot become a canonical security identity. No current ticker or survival information was used to fill that gap.

| Stable refusal code | Filing count |
| --- | ---: |
| SOURCE_ARCHIVE_SIZE_MISMATCH | 210 |
| PARSER_VALIDATION_BLOCKED | 195 |
| DQC_TAXONOMY_UNSUPPORTED | 113 |
| XBRL_ENTRYPOINT_UNRESOLVED | 37 |
| DQC_VALIDATION_UNAVAILABLE | 1 |
| SOURCE_PAYLOAD_INVALID | 1 |

Unsupported taxonomy and absent cached schemas describe validation coverage, not absent SEC financial facts. Original blocking finding codes and source references are retained in the audit, including DQC accounting errors. Representation differences cannot be accepted by blanket whitespace trimming; some differences occur inside fact text. The fixed historical DQC v1 profile supports only its declared literal namespaces. No rule was disabled or severity lowered to improve coverage.

## Exact command and repeat

Both complete executions used the identical command and frozen inputs:

```sh
docker exec value-investment-agent-361-replay-evidence-fundamental-service-1 \
  python /tmp/validate_fixed_history_originals.py \
  --cohort-root /tmp/issue361-fixed-cohort \
  --runtime-pins /tmp/issue361-original-runtime-pins.json \
  --output-directory /var/lib/fundamental/fixed-original-validation-v1
```

Both commands exited 0. The first complete execution resumed the previously interrupted acquisition; the second traversed all 589 retained results. Both produced input digest `9df91d16f1645ee5617177d3dbcf55fd724656c5908d41511566fd23d4c3905a`, output digest `b61a0c24a50032454072b23282eed08df550ac70611b26d90ce00451587d9643`, and report `0a8690b9ef019792cb178aabe4ac70178eb92dd43176220deada4344905c1e0c`.

The complete second execution reported 589 unchanged results, `network_attempt_count=0`, `new_file_count=0`, `new_result_count=0`, all eight database row deltas 0, `existing_mtimes_unchanged=true`, and report `wrote=false`. No canonical snapshot, fact, acquisition or release was published by this diagnostic. Existing unrelated-to-this-diagnostic test rows in this issue-owned database are not claimed to be absent.

## Traceable retained evidence

- [Complete audit](issue-361-fixed-original-validation-v1/complete_audit/c0b694107413b9443f7cc0113ec92e3f0808069678ed6afdd83b5c13fa5ebdc5.json.gz), input `dd77e5813af61467f611827f2ce4bdeebeaca5c7ee6be31854cdeef131b4703e`, output `2783fb84c3f4728897546020f3e252c621e8ec178bf0f9ac65023ffe452293c1`: all 589 canonical results, rejection companions, original inventory/report, all 100 issuer-specific mapping proposal references, per-model limitations and label horizons.
- [Execution receipt](issue-361-fixed-original-validation-v1/execution_receipts/444379b9d05193dd2f4f570b76654dce085c82bedc9e766199929230221c6ac7.json.gz): exact source and observer commits, full controller logs, command/exit results, and the retained audit reference. Its executor source is also retained by digest.
- Re-running the retention executor at the same observer commit exited 0, reused every artifact, created zero files and preserved all bytes and mtimes. This separately verifies evidence packaging, not composer execution.
- [Original runtime tuple](issue-361-original-runtime.json) identifies ports 18661/18662, ordered Compose files, env digests and owned storage. [Current candidate runtime](issue-361-runtime.json) identifies the newer `ea99e6f6cbb52bf58d54e94ebbf88faa707e12e1` source on ports 18663/18664; the 4c diagnostic is not presented as execution of that newer implementation.

## Threshold decision and remaining work

For each of `fcff_dcf` and `transition_fcff_dcf`: canonical forecast coverage is 0/100, complete canonical labels 0, paired independent issuers 0. Forecast error and uncertainty are null because there are no paired predictions; null does not mean zero error. The evidence is **underpowered**, `supported_history_threshold=null`, and canonical forecast availability is **abstain**. Existing candidate valuations remain **provisional** or abstained under the unchanged quality policy. No **verified** threshold or valuation is asserted.

Next: run the same inventory against the latest pinned implementation while reusing original receipts; resolve historical validation/identity in the owning parser/acquisition layer (#371), complete actual issuer/period mapping and historical-policy review (#369), publish trusted canonical releases, and run #352's formal composer replay twice. Full replay acceptance, review/CI and merge-commit verification remain outstanding. PR #370 stays draft, #361 stays OPEN, and issue-owned resources remain available. No #351–#355 acceptance evidence was changed.
