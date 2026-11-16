# Conditional operating labels and comparisons

NEWMARKET's historical originals leave continuing capex and several working
capital classifications unresolved. The owner-approved #418 research path
retains explicit allocations beside the exact study. It grants no mapping,
release, market-policy or history-threshold approval.

Declared model versions must resolve to the initial model specifications and
match the executable FCFF formula graph and numerical policy. Validation and
execution both enforce this binding, including requests passed directly to the
publication functions. Unknown versions and swapped model/version pairs fail
before any forecast or artifact is produced. Scenario replay output v2 records
each resolved model specification's digest; it never echoes an arbitrary caller
version. The operating-target and full-calculation paths use the same resolver.

`OperatingComparisonRequestV1` freezes an existing decision request and a separate
label observation set. The label uses the first subsequent original annual
filing in the pinned chronological inventory, including its prior-year
comparative. It cannot skip an incomplete first original, use an amendment,
combine originals, or replace decision observations with later comparatives.
Equal-availability first originals produce a retained conflict. Inventory
completeness and accounting review require separately retained source evidence.

Both observation sets reproduce facts through the original issuer mapper.
Shared `build_scenario_history` partitions reported parents into operating,
known excluded and unresolved excluded amounts. Unknown debt, investments,
leases and other classifications never become known zeros. The same asset and
liability fractions are assumed across origin and label periods. All capex
fractions remain explicit, including unused baseline capex. Allocation fractions,
rationales, source references and scope evidence remain in the request and output.

`replay_operating_comparison` uses `derive_historical_metrics.realized_fcff`
for conditional labels. Forecasts continue through #352's composer and operating
projection. The comparison pairs identical asset/liability fractions and retains
every explicit target-capex allocation. Signed error is forecast FCFF minus
conditional realized FCFF; absolute error takes its magnitude. Normalized signed
error divides by the frozen origin base revenue, so zero and negative conditional
outcomes remain comparable. Currency and annual-period basis follow the pinned
issuer and first forecast horizon.

These are sampled conditional comparisons, not exact ground truth, confidence
intervals or global bounds. Scenario counts do not increase independent issuer
count. Transition's filed-evidence gate still applies and every refusal remains
in the report. Exact study cases remain zero and `supported_history_threshold`
remains null. #377's research-method approval is separate.

Run the offline CLI from a clean exact-commit checkout:

```sh
uv run --frozen --project fundamental-service python -m \
  fundamental_service.operating_comparison_runner \
  --request /absolute/path/to/frozen-request.artifact \
  --artifacts /absolute/path/to/comparison-artifacts \
  --implementation-commit <full-40-character-SHA>
```

The existing ArtifactStore publishes canonical input, mapping, forecast, label,
comparison and execution-report artifacts using content digests, locks and
temporary-file/atomic-rename writes. Repeating identical commit, request,
command and runtime pins reuses all six artifact types with `wrote=false`.
Execution reports include commit, Python, package and lock pins; different
runtimes may have different report digests while semantic results match.
Generated inputs, sources and reports belong outside Git. Isolated Docker
acceptance executes the installed module; HTTP readiness alone proves only
process health. This offline path neither ingests SEC data nor publishes a
trusted release or a full enterprise valuation.
