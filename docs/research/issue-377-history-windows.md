# Explicit operating history windows (#377)

The operating profile accepts up to five complete trailing annual periods with
a three-period candidate minimum. Its default can therefore prepare from three
periods when five are unavailable. Comparing observed history groups does not
measure a controlled three/four/five-period difference.

`IssuerOperatingReleaseService.prepare(..., history_window_years=3)` requests
exactly three trailing complete periods from the authenticated release. Four
and five are also supported. Omitting the argument preserves the existing
default output, input identity and numerical behavior. Full valuation is
unchanged.

Explicit-window outputs pin `complete-trailing-annual-v1`, the requested number,
actual fiscal years, selected fact IDs and excluded historical fact IDs. All
input facts still bind the input digest. The service verifies the entire release
and preserves existing source, conflict, unit, period, amendment and transition
evidence gates before selecting a shorter history. An invalid older input can
therefore still cause an abstention. Shorter windows do not repair a defective
release.

The existing annual resolver identifies complete trailing periods. The exact
requested count is then required before passing those periods to the existing
historical-metric, #352 assumption-composer and operating-projection functions.
An unavailable window returns `OPERATING_HISTORY_WINDOW_UNAVAILABLE` with no
forecast, tax rate or projected nodes; it cannot silently substitute fewer
periods. Metric and projected-node lineage uses only the retained periods and
required filed transition evidence. Excluded observations remain auditable.

Prepared outputs remain provisional and `supported_history_threshold` remains
null. This is the execution boundary for a future frozen study protocol; it
does not approve loss, precision, power, multiplicity or promotion criteria,
measure real accuracy, or supply missing accounting mappings. Compare windows
on common issuer/date cases with identical original labels and model, mapping
and policy versions, retaining every unavailable case and all-selected coverage.

Boundary tests cover both models and all windows, shared-composer parity,
incomplete windows, rejected/excluded input identity, gaps, conflicts, units,
duplicate facts, transition evidence, serialization, deterministic ordering,
and authenticated release reads after restart without artifact publication.
Generated verification receipts and real-case diagnostic artifacts stay outside
Git. Synthetic release tests do not count as complete study issuers.

## Offline conditional window replay

`scripts/replay_history_study_windows.py` selects the trailing three, four and
five periods from one frozen longest-history conditional request per issuer.
It retains the complete original-source view, mapping manifest, fact inventory,
first-original label and model/policy identities. It trims only the selected
periods and their already explicit capex fractions. It never creates older
observations or estimates a missing allocation. A shorter seed leaves the longer
windows explicitly unavailable.

The tool calls the existing Fundamental scenario and conditional-label functions.
The reviewed evidence exporter validates every generated arm before publication.
An invalid source, unavailable Transition model or incomplete label remains in
the official results; executing an arm does not imply a numerical prediction.
All 100 selected issuers and missing windows remain in the exporter's loss panel.

The seed index pins `history-study-window-seeds.v1`, the unchanged fixed manifest
digest, installed runtime/lock pins and content-addressed comparison requests.
Run from a clean exact commit with inputs and outputs outside the checkout:

```sh
PYTHONPATH=fundamental-service/src:scripts python scripts/replay_history_study_windows.py \
  --manifest /external/frozen-manifest.json \
  --seed-index /external/window-seeds.json \
  --exact-commit <implementation-sha> \
  --output-directory /external/history-windows
```

The generated evidence index feeds `export_history_study_evidence.py`, followed
by `analyze_history_study.py`. Canonical content identifies each request, forecast,
comparison, index and report. Publication reuses the existing locked atomic
publisher. Repeating a completed run returns `wrote=false`; resuming after a
partial publication reuses completed files without changing their bytes or mtime.
The tool has no acquisition fallback and changes no database, trusted release,
runtime service or threshold policy.

## Source-bound seed extension

`scripts/compile_history_study_seed.py` adds exactly the immediately preceding
annual period to a frozen three- or four-year conditional comparison request.
Its `history-study-seed-extension.v1` input contains one complete original issuer
report, nine distinct provisional observation mappings, aligned annual dates, a
new mapping version, explicit scope assumptions and an allocation for each
retained parent scenario. Source and parser identities must resolve through the
existing Fundamental mapper at the unchanged decision cutoff. Future originals,
missing scenarios, mismatched observations and claimed mapping approval fail.

The compiler reproduces every existing fact through the formal mapper, requiring
all fields except mapping and fact identity to remain equal. Labels, original
filing inventory, model versions, financial policy and existing allocation values
remain bound to the seed. New allocations are explicit conditional inputs. The
compiler performs no valuation calculation, source acquisition or release review.

```sh
PYTHONPATH=fundamental-service/src:scripts python scripts/compile_history_study_seed.py \
  --seed /external/frozen-comparison.json \
  --extension /external/source-bound-extension.json \
  --exact-commit <implementation-sha> \
  --output-directory /external/compiled-history
```

Keep the canonical seed and extension outside Git. The command requires a clean
exact commit, pins their content digests and installed runtime, and publishes a
canonical request plus a provenance report with the existing atomic publisher.
An identical rerun reuses both files with `wrote=false`. Publication status is
excluded from semantic result identity. The request can then enter the window
replay and evidence exporter above; it cannot authorize trusted release or
increase the number of independent issuers.

## NEWMARKET four-year source investigation

The original accession `0001282637-14-000003`, available
`2014-02-19T15:03:25Z`, contains the candidate 2012 observations needed before
the unchanged 2016 decision. New retained SEC HTTP 200 receipts bind its index,
direct XML and ZIP. Fresh offline parses of the direct and archived XML, using
the same retained archive DTS, each produce 2,508 facts with the identical
complete semantic digest
`44f3b4453b97167ea6848d2f22b32e6100c7ff427cb9c5e3a2a056655ba2a1af`.
The raw XML digests differ; semantic equality does not assert byte equality or
independent capture of every direct DTS file.

The initial parses retain 48 `DQC.US.0001.51` findings with original error rule
severity, and their `PARSER_VALIDATION_BLOCKED` refusals remain evidence. After
the owning parser correction in #427, an offline replay with the pinned official
GAAP 2013 profile reproduces all 2,508 facts unchanged with no blocking findings.
That source replay permits provisional mapping, not mapping approval or release.
Original-bound proposals retain the 2012 observations and the exact passage for
rounded discontinued D&A.

The [official pinned DQC rule source](https://github.com/DataQualityCommittee/dqc_us_rules/blob/cafb54391c1d21e4c219bc3d491b855a9b877cb6/dqc_us_rules/dqc_us_0001.py)
matches the locally pinned bytes (SHA-256
`9a428c1a045cfe3ca9d9652031310967003a9d7c69bd06aaa50e5f2ebc19bce9`).
Rule version 3.3.1 has taxonomy configurations for 2014–2017; the filing's 2013
taxonomy uses the generic fallback. Its fair-value hierarchy member restriction
produces the observed pension findings. The #427 correction checks original
taxonomy/member definitions and applicability in the parser layer; it preserves
the original rules and findings instead of reducing severity to obtain a pass.
Its historical profile remains taxonomy-specific; success for GAAP 2013 does
not establish compatibility for GAAP 2012 or 2011.

The four-year exploratory extension retains all 125 prior allocations and adds
an independent five-point 2012 continuing-capex fraction grid, producing 625
conditional scenarios. The 2012 original reports gross PPE capex of 38,753,000;
its cash-flow scope combines continuing and discontinued operations. Segment
reconciliation is retained but does not establish the exact continuing cash
split. No scenario is selected as truth, a probability distribution or a global
bound. Both three- and four-year arms can run through the existing #352 composer
with this shared manifest. Transition retains its missing verified filing
evidence abstention. Conditional errors compare stated assumptions and are not
exact ground-truth forecast errors.

Five-year evidence also lacks a complete compatible 2011 original role set and
resolved productive-assets/PPE capex and discontinued-operation scope. Do not
combine incompatible originals to fill it. Keep the three- and four-year
conditional arms, the unavailable five-year arm and every source finding. Conditional
comparisons remain one issuer; complete exact cases remain zero and
`supported_history_threshold` remains null.
