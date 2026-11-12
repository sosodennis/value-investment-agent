# Issue 418: source-bound operating scenarios

Status: WIP, implementation and local acceptance complete; independent review and
CI remain pending. Refs #418, #376 and #377. This increment adds the owner-approved
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

- CI and independent review, followed by integration/main verification.
- Transition filed operating evidence remains a separate source/review gate.
- First eligible original label and conditional scenario comparison need their
  own explicit label scope; exact labels/errors are still unavailable.
- #377 protocol proposal is not approved. Freeze/review error, precision and
  within-issuer history comparison rules before using outcomes for threshold
  selection; then expand the unchanged 100-issuer cohort.
- `supported_history_threshold=null`; complete exact study cases remain 0/100.

## Exact implementation evidence

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
