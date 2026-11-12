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
