# Issue 418: source-bound operating scenarios

Status: WIP, conditional labels and comparison acceptance complete; independent
review and serial integration remain pending. Refs #418, #376 and #377. This increment adds the owner-approved
scenario study alongside the exact study. It does not complete #376, approve
an accounting mapping, authenticate a release, or promote a history threshold.
The original exact-path abstentions and all 100 issuers / 589 targets remain.

## Boundary and implementation

Fundamental Service owns `operating_scenario_contracts`, `operating_scenarios`
and `operating_scenario_runner`. The contracts pin the source view, immutable
canonical observations, original mapping manifests, policy, model versions,
protocol and prospective grid. The shared original mapper must reproduce each
retained observation, including computed accounting evidence. This reproduction
does not prove that an unreviewed accounting classification is correct.

Each period selects the latest original containing the complete required role
set. Every selected role must reproduce the shared conflict selector within that
original. The full decision inventory, including unused observations, binds the
input digest. Future originals, foreign issuers, amendments, mismatched units,
unreproducible values, ambiguous facts and impossible parents retain explicit
refusals. No replacement issuer, filing or missing-tag zero inference is allowed.

`EstimatedOperatingInputsV1` carries hypothetical capex and operating working
capital into `derive_historical_metrics`; it never creates a verified canonical
fact. Existing exact callers retain their metric calculations. Both scenario
models reuse #352 `compose_forecast_assumptions` and `project_operating_nodes`.
Transition's existing filed-evidence gate still applies. There is no new Agent,
UI, market-policy, valuation route, release authority or FCFF formula.

Asset residual after reported cash and total current liabilities are each split
jointly into operating and unresolved excluded balances. Each partition conserves
one same-filing parent. Capex uses an explicit nonnegative continuing/other cash
payment allocation. Unknown investment, debt, lease and other classifications
remain visible even when a scenario assumes an endpoint allocation. None of the
sampled scenarios establishes those accounting classifications or their absence.
Affirmative borrowing disclosures and uncertain parent membership remain in the
source audit; sampled feasibility is conditional on the stated assumptions.

## Frozen NEWMARKET case

- Issuer: CIK 0001282637. Decision: `2016-02-12T16:26:17Z`.
- Decision originals: `0001282637-15-000004`, `0001282637-16-000028`.
- Original label accession `0001282637-17-000005` stays outside the decision
  request. This increment publishes no exact FCFF label or forecast error.
- 52 observations; three periods, 2013/2014/2015; 125 fixed scenarios and two
  model attempts per scenario. The scenarios use constant asset/liability
  fractions and 2013 capex allocations of 0/25/50/75/100%. All 2014/2015 capex
  is conditionally continuing in this grid, explicitly an unreviewed assumption.
- Scope digest: `a79a46a6eb4e40eb644dcc5be5c71c2c4e98edd20039cbab3883d900150c38b1`.
- Input digest: `206c1116eb56351c2e46f5637f52697723564babcf7cdf81d22d834b32388d68`.
- Mapping digest: `ca6e022a43805f338743e406c43e03d4b13cae2eafdb87f17c202ff306e7c11f`.
- Executable policy: `nonnegative-parent-partitions-v1`; source selection:
  `latest-complete-original-per-period-v1`; protocol:
  `newmarket-fixed-parent-sensitivity-grid-v1`.

The scope was recorded in [#418 before acceptance](https://github.com/sosodennis/value-investment-agent/issues/418#issuecomment-6822810921).
Generated evidence stays outside Git at
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-418-scenario-evidence`.
Its `references/build_newmarket_scenarios.py` verifies the retained source and
mapping-report hashes and freezes inputs without running the forecast.

The output describes sampled scenarios only. It is neither a confidence interval
nor a proof of global bounds. Reported rounding and unknown classifications are
not resolved by sampling. No central scenario is truth and no assumed label may
be used as exact threshold ground truth. #415/#416 remain open; this research
output cannot authorize their disputed mappings or an exact release.

## Replay and verification

Run from the clean implementation checkout with the exact commit argument:

```sh
uv run --frozen --project fundamental-service python \
  -m fundamental_service.operating_scenario_runner \
  --request /absolute/path/to/frozen-input.artifact \
  --artifacts /absolute/path/to/isolated-replay-artifacts \
  --implementation-commit <exact-implementation-sha>
```

The runner records exact Git SHA, Python/package versions, lock digest and
command. It writes canonical input, mapping, forecast and execution report
artifacts through the existing locked content-addressed `ArtifactStore`, which
fsyncs temporary files before atomic rename. A repeat reuses identical artifacts
with `wrote=false`. No timestamp, random value or run ID identifies research data.

Acceptance must record clean exact-commit lint/format/types, both architecture
guards, shared-metric/forecast regression tests, source/constraint/failure tests,
real repeat input/output digests and byte/size/mtime inventory comparison. Use a
new Compose project and ports for image/service/PostgreSQL verification; preserve
other projects. Attach the exact commands and results externally. A healthy
service is not evidence of reviewed source mappings or a completed empirical study.

## Remaining acceptance

- Independent review, followed by integration/main verification.
- Transition filed operating evidence remains a separate source/review gate.
- Conditional labels/comparison now have a frozen scope and passing replay.
  Exact labels/errors and reviewed classification evidence remain unavailable.
- #377 protocol proposal is not approved. Freeze/review error, precision and
  within-issuer history comparison rules before using outcomes for threshold
  selection; then expand the unchanged 100-issuer cohort.
- `supported_history_threshold=null`; complete exact study cases remain 0/100.

## Earlier forecast-only evidence

Implementation `0c686d18c22af54f53379a646191114b157f923d` passes 1,590 tests
against an isolated PostgreSQL database, with 11 explicit optional SEC-resource
skips and one expected duplicate-ZIP warning. Ruff, six-file formatting, mypy,
both architecture guards and `git diff --check` pass. All command/exit-code and
input/output digests, including the rejected abbreviated-SHA invocation, are in
[the checkpoint](issue-418-checkpoint.json); raw outputs remain outside Git.

| Result | Evidence |
| --- | --- |
| FCFF | 125 provisional scenario results; 25 distinct first-year FCFF values |
| Transition | 125 abstentions, all `TRANSITION_EVIDENCE_MISSING`; inputs retained |
| Independent issuers | One with conditional scenarios; zero complete exact cases |
| First-year FCFF sampled range | USD 173.32m–191.31m, conditional assumptions only |
| Full desktop repeat | Four artifact types reused, `wrote=false`, zero new artifacts; bytes/sizes/mtimes unchanged |
| Container repeat | Same input/output as desktop, zero network requests, second run `wrote=false` and unchanged files |
| Docker isolation | New project, ports 28418/25418, network and two new disposable volumes |
| Cleanup | Only #418 containers/image/network/volumes removed; all 67 pre-existing container IDs/image IDs/start times equal baseline |
| CI at metadata head `381cf2b3b4c4e454746f114e7a56d73b23cb34d1` | [12 jobs passed](https://github.com/sosodennis/value-investment-agent/actions/runs/43214447271), release gate skipped; no reviewer yet |

Numeric output digest:
`ffdc58976027a7b1d0429edf44242ddb8e4e9389c1a99d35935600e93fd60811`.
Desktop report digest:
`1e7f3f8cdbded2c9a918b74b0c3dd724b21ece62209b4886a1bcd4de30303c1f`.
The container's Python 3.12 runtime differs from desktop Python 3.11, so its
execution report has a distinct identity; numerical output remains identical.
All 77 Python source files inside the image matched the implementation checkout.
HTTP `/readyz` and published ports were checked, without claiming configured
SEC ingestion or a reviewed data release. This adds no public service route.

Sensitivity audit reveals that baseline 2013 capex is not consumed by this
three-period forecast: each of 25 working-capital allocations has five identical
forecasts across its five 2013-capex assumptions. Reinvestment lineage consumes
2014/2015 capex only. This is evidence for an owning-layer requirements review in
[#415](https://github.com/sosodennis/value-investment-agent/issues/415#issuecomment-6823019276),
not an exemption from its current release contract. Scenario count cannot be
used as independent sample count or forecast-error evidence.


## Conditional labels and comparison: current checkpoint

Implementation `20722aa2ecdce183cfc17cbf55adad501bc87ec0` extends the frozen
forecast with a separate first-original label partition and paired comparison.
The design was recorded [before outcomes](https://github.com/sosodennis/value-investment-agent/issues/418#issuecomment-6825987895).
[Usage and basis](../../fundamental-service/docs/conditional-operating-comparisons.md)
explain the allocation, same-filing comparative and normalization rules.
[The current compact checkpoint](issue-418-conditional-checkpoint.json) preserves
exact commands, commit, digests, runtime, successful checks and retained failures.
The earlier checkpoint remains the historical forecast-only receipt.

The first label original is `0001282637-17-000005`, available
`2017-02-15T14:59:50Z`, for 2016-12-31. It provides 30 retained observations,
including 2015 comparative balances. That later filing reports 2015 current
assets of USD768,392,000; the original forecast retains its origin balance of
USD774,767,000. The retained normalized SEC submissions snapshot has 20 annual
filings and confirms this accession as the first subsequent original in the
fixed case. This cross-check does not claim fresh acquisition or raw response
reconstruction. Source audit `90b567152cbdf7d7202ce6b627e89de389ba0c39a1b8ed8a38590c4212c762ca`
retains the separate source-byte/binding/mapper checks.

Labels reuse `derive_historical_metrics.realized_fcff`. Identical constant asset
and liability fractions pair decision and label scenarios; all five explicit
2016 continuing-capex fractions remain. Label baseline2015 capex is explicitly
100%, although it is not consumed by realized2016 FCFF. The existing origin
assumption of full continuing2014/2015 capex remains conditional and unreviewed.
A joint residual never proves that missing debt, investment or lease amounts
are zero. No scenario winner is selected.

| Conditional result | Count / status |
| --- | --- |
| Conditional labels | 125 provisional; 30 source observations retained |
| FCFF comparisons | 625 provisional conditional comparisons; zero refusals |
| Transition comparisons | 625 abstentions with `TRANSITION_EVIDENCE_MISSING` |
| Independent issuers | One with conditional comparisons; zero with Transition comparisons |
| Sampled conditional realized FCFF | USD159.28m–363.30m |
| Sampled signed difference (forecast minus conditional realized) | USD−182.55m to +24.60m |
| Sampled absolute difference | USD1.12m–182.55m |
| Normalized signed difference / origin base revenue | −8.53% to +1.15% |
| Exact study / threshold | 0/100; `supported_history_threshold=null` |

These are sampled conditional comparisons, not exact forecast errors,
confidence intervals or global bounds. Scenario counts do not increase the
independent issuer count. #377's method review and #415/#416 evidence remain
separate. The numerical spread reveals sensitivity to unresolved assumptions;
it supplies no history-threshold approval.

Pinned input: `c4b5b12bf6924fe225f4a75a14fbba2c52bb48b633269042679a029a86ea0df8`.
Label input: `93439231481e2cf677be33d0b4539320a96849bda41d0dbef6403a83c3054707`.
Scope: `663957b3a7a93ff38337ebdc5d81efe53427e47925a0777cb61c75b689f30ecf`.
Label policy: `120ba70ec804dc4df70353dc7c3c5cff9997b5f0470e38a52d458cd514e83f08`.
Comparison output: `0ceff1ee6e77a98638a0a76fc5ae804fac9459c6b372ec08cf265970071d49eb`.
Frozen forecast output remains
`ffdc58976027a7b1d0429edf44242ddb8e4e9389c1a99d35935600e93fd60811`.

Two fresh desktop processes reused all six input/mapping/forecast/label/comparison/
report artifacts on the second complete execution with `wrote=false`, unchanged
bytes/sizes/mtimes, identical classifications/order/statistics and zero network
requests. The installed image matched all 92 Service Python files. Container
repeats and service restart retained the same semantic output and all artifacts;
container execution report `3b6e0084707f715b8defd12cfba8abed16ad1d0cc6ef613f286735dadb12c870`
differs from desktop report
`9d2ebe0b91319bbeaa80d8bb00220c38b9d3bf27508b0a240f3c0fd821d44179`
because runtime/command pins differ.

The isolated project `value-investment-agent-418-conditional-labels` used
ports28419/25419, one network and two disposable volumes. HTTP readiness and
1,790 Service/PostgreSQL tests passed; 11 optional SEC-resource tests skipped
explicitly, with one expected duplicate-ZIP warning. Ruff, format, six-source
mypy, both architecture guards and diff passed at the exact implementation.
[CI43237022208](https://github.com/sosodennis/value-investment-agent/actions/runs/43237022208)
passed all12 applicable jobs; release gate skipped. HTTP readiness had SEC
identity resolution disabled: this is installed offline-module acceptance,
not SEC ingestion, trusted release, or complete enterprise valuation acceptance.

Only this disposable project's containers/image/network/volumes were removed.
All69 pre-existing container IDs, image IDs and start times equal their initial
baseline. An external cleanup-helper syntax failure occurred before mutation;
its exit1 receipt is preserved alongside the corrected exit0 result. External
driver versions and raw command outputs remain content addressed outside Git at
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-418-scenario-evidence/conditional-delivery-20722aa2`.

Independent engineering review and serial parent integration have been requested
from the main chat. Keep PR420 draft and #418/#376/#377 open until the relevant
review, integration and main-delivery criteria pass. No accounting signature or
mapping-quality promotion is claimed by this checkpoint.
