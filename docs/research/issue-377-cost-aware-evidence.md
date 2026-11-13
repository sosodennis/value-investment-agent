# Cost-aware evidence choices for the fixed history study

The fixed #376/#377 study can deliver useful conditional results while exact
accounting evidence remains incomplete. Acquisition cost and the intended claim
determine which increment to pursue. The approved conditional route preserves
the exact study, all fixed issuers, and `supported_history_threshold=null`.

This document records external calibration and the practical alternatives for
review. It changes no executable method, primary input policy, numerical margin,
sample gate, trusted release requirement, or promotion authority.

## Match acquisition effort to the claim

Before another acquisition attempt, identify the unresolved decision and the
evidence that could change it. Compare the original-source route with a sourced
estimate, conditional scenarios, a narrower claim, and an explicit abstention.
Record the expected benefit, access constraints, observed acquisition effort,
assumptions, and stopping condition in the owning issue. Reuse frozen evidence.

Search primary literature and official guidance when repeated failures suggest
a wrong premise, a costly classification requirement, or an unsuitable check.
Record what the source supports and what remains a project decision. Web research
can justify a method; it cannot supply missing historical facts or threshold
ground truth. A changed accounting or promotion policy needs a reviewed version.

No monetary or acquisition-time comparison has been measured for these options.
The alternatives below describe evidence costs and claims, not quantified savings.

| Current gap | Practical alternative | Result the evidence can support |
| --- | --- | --- |
| NEWMARKET operating receivables, accrued liabilities, contract assets, and deferred revenue lack exact classification evidence | Use the existing versioned composite working-capital route with explicit exclusions and conditional residual fractions. Seek additional originals when they can resolve a material assumption. | Conditional FCFF comparisons with the assumptions retained. Unknown components remain unknown. |
| NEWMARKET 2013 continuing capex lacks a verified split | Retain the approved capex scenarios. Assess whether a narrower source-supported range would change the decision before further manual extraction. | Results conditional on the capex scope. A scenario grid alone establishes neither a probability distribution nor exhaustive bounds. |
| Transition inputs remain unavailable | Deliver the working FCFF increment and retain every Transition refusal. | A bounded FCFF delivery. Transition completion and evidence remain separate. |
| Nine original labels are missing and one issuer has a 731-day horizon mismatch | Retain all 100 issuers and the original label policy. Consider a reviewed precision-based claim for the eligible subset. | Coverage for all selected issuers and errors for explicitly eligible cases. The unchanged legacy 100-complete-pair gate still fails. |
| Four- and five-year evidence is missing from the conditional case | Acquire and map the required pre-origin originals if the history comparison warrants the effort. A revenue-first increment is a separate candidate for method review. | No history-length conclusion from the existing three-year case. A revenue result would support only its own model and target. |

Conditional results already seen remain exploratory. Select a primary policy
from accounting and economic justification, rather than its favorable error.
Forecasts and conditional labels can share classification assumptions, so a small
error does not independently validate those assumptions. Review their lineage
and sensitivity together. Scenario counts never increase the issuer count.

## External methods and their limits

[Damodaran's scenario analysis](https://pages.stern.nyu.edu/~adamodar/pdfiles/papers/probabilistic.pdf)
supports valuation under explicit alternative assumptions and inspection of
important sensitivities. Joint assumptions must be economically feasible.
Scenario probabilities require evidence. The existing conditional grid has no
authority to report calibrated prediction intervals or an expected-value policy.

[Hyndman's rolling-origin material](https://github.com/robjhyndman/fpp3_slides/blob/5db37d7198d34267bd098d65179390cae75e0d80/5-10-tscv.Rmd)
supports out-of-sample comparison at relevant horizons.
[His accuracy material](https://github.com/robjhyndman/fpp3_slides/blob/5db37d7198d34267bd098d65179390cae75e0d80/5-8-evaluating_point.Rmd)
supports naive benchmarks and training-only scaled errors. MAPE is unsuitable
near zero and problematic for negative outcomes. Neither source approves the
project's proposed 0.10 MASE margin. Lack of a significant difference does not
establish history-length noninferiority.

[Cameron and Miller](https://cameron.econ.ucdavis.edu/research/Cameron_Miller_JHR_2015_February.pdf)
explain how within-cluster dependence affects inference. The v4 method resamples
issuers together with their paired history arms. Cross-issuer industry and period
dependence remains a review question. One hundred issuers at the fixed origins
do not establish robustness across economic regimes. Cluster definitions and
effective sample size need justification before a broader uncertainty claim.
This finding introduces no automatic replacement of the frozen bootstrap.

[SciPy's bootstrap reference](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html)
describes paired resampling, interval methods, and degenerate distributions.
More bootstrap replicates reduce simulation noise; they do not add observations.
Interval adequacy can be assessed with an independent implementation and
simulation under plausible tails, dependence, and missingness. No universal
finite-sample guarantee follows from a successful tool run.

[XBRL US DQC](https://xbrl.us/home/priorities/data-quality/rules-guidance/)
provides rules, effective dates, and Arelle/XULE tooling. Historical checks need
a documented applicable profile. DQC results assess tagging and consistency;
accounting classification and forecast validity require their own evidence.

[Federal Reserve SR 26-2](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm)
and its [attachment](https://www.federalreserve.gov/supervisionreg/srletters/SR2602a1.pdf)
support validation proportionate to model use, materiality, and risk. SR 26-2
supersedes SR 11-7 and SR 21-8. It is supervisory guidance aimed mainly at larger
banks, not an enforceable standard or certification for this project. Its model
validation principles are useful references for conventional financial models;
generative and agentic AI are outside its scope.

## Apply the calibration to the current delivery

The [conditional evidence adapter](issue-377-evidence-adapter.md) already replays
formal requests and preserves every conditional result and refusal. Independent
review and serial integration can assess that bounded delivery without waiting
for exact FCFF classification or a successful threshold study.

The [v4 methods](issue-377-methods-v4.json) remain unchanged and exploratory.
Before promotion, review the business meaning of the margins, the primary policy,
the infeasible legacy gate, dependence, interval adequacy, and missingness scope.
Additional temporal origins require a separately frozen manifest. No fixed
issuer, decision date, original label, or failure is replaced by this calibration.

Raw method documents and source-digest receipts are retained outside Git at
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/issue377-external-calibration/`.
The [acceptance checkpoint](../acceptance/issue-377-design-checkpoint.md) records
the retrieval identities and documentation checks. Source snapshots establish
which method references were inspected; they grant no review or release approval.
