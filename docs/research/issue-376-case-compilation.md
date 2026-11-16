# Original-bound operating case compiler (#376)

`scripts/compile_operating_case.py` converts an explicit canonical case plan into
the existing Fundamental conditional forecast/label request. It introduces no
financial formula, mapping approval or release. Generated plans and reports
remain outside Git. The formal composer and existing accounting partitions own
all forecast, realized FCFF and error arithmetic.

The plan supplies original evidence, provisional source-bound mappings, fiscal
calendars, an explicit allocation grid, assumptions, model versions and the
unchanged first-original inventory. The shared accounting extractor retains
source candidates and conflicts. Segmented observations remain in the extraction
audit, while the existing issuer-identity predicate excludes them from issuer
inputs. The compiler records those excluded IDs; it cannot discard a conflicting
consolidated value to obtain a result.

Fundamental Service's `select_scenario_periods` reuses the exact existing latest
complete-original and annual canonical selection, then checks each selection
through the existing explicit period validator. The existing numeric path and
v1/v2 scenario policies retain their behavior. Fiscal gaps, multiple period
shapes/concepts, equally available conflicting values, future/amended sources
and missing roles fail rather than receive defaults. A selected original may
contain more dates and concepts than the plan uses; the complete original and
initial review packet retain that evidence. Source-bound mapping scope must
state its annual/instant/consolidated selection explicitly.

The compiler does not infer that aggregate D&A is continuing, cash capex excludes
discontinued activity, taxes are operating, or missing balances equal zero.
Those judgments belong in the cited accounting review or explicit scenario
assumptions. A successful conditional case is not a trusted release. The existing
`fundamental-sign-mapping-review` requires an already approved mapping, genuine
independent review and a matching trusted key; a local signature cannot invent
these facts. Deployment trust and private keys are not changed by this tool.

## Versioned transition source references

The original `unreviewed-filed-operating-disclosures-v1` policy and digest remain
the default. Explicit `unreviewed-filed-operating-disclosure-groups-v2` accepts
the standard combined organization/consolidation/accounting-policies text block
when the narrower consolidation text block is unavailable for the current
consolidated annual period. Both versions require the separate segment disclosure
and the latest original. A deterministic group preference selects the narrower
concept when both are available; duplicate selected observations fail. The v2
audit retains every alternative observation digest, including other periods.

This is a generic standard-concept source-reference policy, without issuer
branches or text-derived parameters. Exact text, namespace, issuer, period,
parser observation, source hash and provisional status are checked. It supplies
conditional source lineage only. Model suitability, independent accounting
review and full valuation release remain unestablished.

## Reproduce

From an exact clean implementation commit, compile a canonical externally
retained plan with its SHA-256:

```sh
python3 -B scripts/compile_operating_case.py \
  --plan /absolute/external/plan.json --plan-digest <sha256> \
  --exact-commit <full-tested-commit> \
  --output-directory /absolute/external/compiled
```

The report includes the typed request, decision and label extraction packets,
excluded IDs, accounting assumptions, runtime and input/output identities. A
repeat reuses the same artifact with `wrote=false` through the existing locked
temporary-file/atomic-rename publisher. Feed its request into the existing
`fundamental_service.operating_comparison_runner`, retaining the separate
forecast, mapping, label, comparison and report publications.

If the source-reference policy is needed, explicitly compile the request with:

```sh
python3 -B scripts/compile_transition_disclosures.py \
  --seed /absolute/external/request.json \
  --disclosure-policy unreviewed-filed-operating-disclosure-groups-v2 \
  --exact-commit <full-tested-commit> \
  --output-directory /absolute/external/disclosures
```

Re-run the complete comparison twice. Every existing artifact must return
`wrote=false` and preserve bytes and mtimes. Keep all issuer failures and
unavailable 4/5-year windows. One issuer with many scenarios still counts as one
conditional issuer; the exact-release count and supported threshold stay separate.
