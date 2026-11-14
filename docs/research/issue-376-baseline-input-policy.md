# Decision-baseline capex dependency (#376/#425)

The `baseline-unconsumed-capex-v2` policy permits an explicitly unknown capex
amount in the earliest **decision** period. The formal historical metrics use
that period's revenue, margin, tax and working-capital balances, but calculate
FCFF and reinvestment only from the second period onward. No formula, composer
version or model version changes.

The request must explicitly use `fundamental.operating-scenarios.v2` and its
matching policy digest. `ScenarioPeriodV1.unconsumed_capex` carries a typed
`unknown_unconsumed` object with the selected original's content hash, evidence
digests and classification rationale. That period has eight observed roles and
no capex fact ID, number or scenario allocation. Every later period still needs
all nine roles from one eligible original, including classified gross PPE capex.
The explicit `latest-complete-original-per-baseline-family-v2` source policy
selects the baseline's latest complete five-role flow original separately from
its latest complete three-role working-capital stock original. Each family must
still come from one original; equal-availability ambiguity refuses. The marker
binds the stock original. This permits continuing-basis restated flows already
available at the decision date while retaining older stock balances. It does
not apply to later periods or labels.
The shared metrics boundary rejects a nonoperand outside the matching provisional
research baseline. Unknown is never zero and never a canonical fact.

This does not permit replacing `PaymentsToAcquirePropertyPlantAndEquipment` with
`PaymentsToAcquireProductiveAssets`: the latter also covers software/intangibles.
Retain the broader reported amount in original evidence and explain the unresolved
scope. Do not mix originals to manufacture a complete role set.

`history-study-seed-extension.v2` adds exactly eight source-bound provisional
mappings and the typed nonoperand. Each existing scenario survives once with its
original identity; no unknown-value grid is invented. The offline compiler binds
the expanded mapping manifest and changes the decision policy explicitly. Derived
three/four/five-year arms share that policy and the unchanged first-original label.
Observed baselines in shorter arms keep their explicit capex allocations.

The combined request uses `fundamental.operating-comparison.v2`; new scenario and
comparison results use replay versions v3 and v2 respectively. The existing Python
contract classes parse these explicitly enumerated versions. Old request/replay
versions keep their exact serialized bytes and policy digests; the optional marker
is omitted when absent. Old artifacts are retained and are not reinterpreted.

Conditional labels retain their strict v1 allocation policy and require observed
capex in both periods. Complete/full valuation, authenticated releases, mapping
reviews, Transition's filed operating evidence and caller approval remain separate
gates. Neither policy grants source approval or verified quality.

The first case is fixed to NEWMARKET CIK `0001282637`, origin
`2016-02-12T16:26:17Z`. Its 2012 annual original provides the three 2011 stock baseline
observations under the corrected GAAP 2012 validation profile; continuing flow
observations come from the already-retained 2013 original, including its explicit
D&A exclusion mapping. The older original's gross revenue/operating profit/tax
values differ from that restatement and remain audit evidence. The original
findings, capture-receipt discrepancies and unresolved classification evidence
must remain in the audit bundle. Generated originals, mappings, requests and full
numeric panels stay outside Git. Exact study cases remain 0/100; one conditional
issuer and hundreds of scenarios cannot establish `supported_history_threshold`.

Preimplementation design:
[issue #376](https://github.com/sosodennis/value-investment-agent/issues/376#issuecomment-6849553765)
and [issue #425](https://github.com/sosodennis/value-investment-agent/issues/425#issuecomment-6849554565).
Acceptance must record the exact clean commit, commands, runtime pins and all
input/output digests; repeat replay must reuse unchanged immutable artifacts.
