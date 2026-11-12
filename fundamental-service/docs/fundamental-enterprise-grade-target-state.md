# Fundamental valuation service target state

Status: canonical normative specification for the implemented service and future family releases
Owner: Fundamental service maintainers
Scope: independently deployable domain service in `fundamental-service/`
Last reviewed: 2026-11-05

This file is the single source of truth for the Fundamental domain service. It defines its contracts, model families, quality states, valuation boundaries, calibration protocol, verification evidence, and release gates. Runtime code implements only the explicitly released coverage; exploratory families remain unsupported until their complete evidence and promotion gates pass. A backlog item, runbook, research note, or implementation comment may add operational detail, but it must not define a conflicting rule. When another document conflicts with this file, this file wins.

Existing Fundamental documents under `finance-agent-core/docs/` describe the current agent or provide historical and operational context. They do not define the new service. Do not create another design document for the same problem. Update this file first, then update code and any command-level runbook that is still needed to operate the service.

## 1. Purpose

The target system produces an intrinsic-value estimate only when it can answer all of these questions:

1. Which issuer, security, currency, share class, and valuation date were used?
2. Which raw filing facts and public observations produced each input?
3. Were those facts available at the valuation time, or did a later restatement leak into the result?
4. Why is the selected model appropriate for this company and this data coverage?
5. Which deterministic formulas produced the result, with what units and rounding rules?
6. How uncertain is the result, and are the stated intervals calibrated on out-of-sample data?
7. Which checks passed, which warnings remain, and when must the system abstain?
8. Can another implementation reproduce the result from the recorded inputs and versions?

The system must support free and public data sources. Paid APIs are not a requirement and must not be hidden in a production path. A provider that is free but unstable, scraped, or legally restricted is an optional degraded source, not a foundation for verified valuation.

## 2. Non-goals

This specification does not promise that an intrinsic value is the future market price. Market prices, analyst targets, and consensus estimates are observations or comparison signals. They are not ground truth for intrinsic value.

This specification does not require one universal valuation formula. The system must reject a model that does not fit the company or the available facts, even when a fallback formula could produce a number.

This specification does not allow an LLM to choose or alter a numeric result after the deterministic calculation boundary. Agents may resolve identity, gather evidence, propose assumptions, and explain a result. The calculation engine consumes a validated typed input and executes pure deterministic functions.

## 3. Definition of a reliable Fundamental service

The target is reliable only when all of the following hold for a released valuation artifact:

- **Identity correctness.** The issuer, security, exchange, share class, and currency are resolved and disambiguated.
- **Point-in-time correctness.** Every observation carries `as_of`, `available_at`, and source filing timestamps. Historical replay uses only information available at the decision time.
- **Accounting correctness.** XBRL facts retain the concept, unit, period, dimensions, filing accession, taxonomy, and source URL. Extension concepts are mapped with an auditable rule.
- **Quality visibility.** Missing, contradictory, stale, restated, estimated, or provider-fallback values have machine-readable status codes.
- **Model applicability.** A model declares required inputs, forbidden conditions, acceptable ranges, and an abstention rule. Selection cannot silently default to `dcf_standard` when no valid candidate exists.
- **Calculation integrity.** The engine checks units, signs, denominator limits, share scope, capital structure, and formula invariants before emitting a value.
- **Uncertainty honesty.** Scenarios and intervals come from explicit assumptions and calibrated error distributions. The system does not report false precision.
- **Traceability.** A user can follow every output field to source facts, transformations, assumptions, code versions, and quality decisions.
- **Reproducibility.** A pinned input snapshot and runtime manifest reproduce the same artifact or explain any intentional nondeterminism.
- **External verification.** Golden fixtures, independent formula checks, public-source reconciliation, and out-of-sample monitoring support the release decision.

## 4. Existing agent baseline and known risks

The current workflow is a linear graph:

```text
financial_health -> model_selection -> calculation
```

The current agent graph is defined in [`finance-agent-core/src/agents/fundamental/workflow/graph.py`](../../finance-agent-core/src/agents/fundamental/workflow/graph.py), and its state is defined in [`finance-agent-core/src/agents/fundamental/workflow/state.py`](../../finance-agent-core/src/agents/fundamental/workflow/state.py). These files are baseline evidence only. The new service owns its model selection, data quality, calculations, and provenance. The agent calls the service through a versioned contract after the service passes its release gate.

The current registry contains `dcf_standard`, `dcf_growth`, `saas`, `bank`, `reit_ffo`, `residual_income`, `eva`, `ev_revenue`, and `ev_ebitda`. The registry is useful as a starting inventory. It is not proof that each model has complete accounting coverage.

The following risks are current code facts that the target must remove or explicitly expose:

- [`dcf_common.py`](../../finance-agent-core/src/agents/fundamental/capabilities/core_valuation/domain/engine/graphs/dcf_common.py) accepts `sbc_rates_converged`, validates its length, and then does not include SBC in `calculate_fcff`. The target must choose and record one policy for SBC expense, add-back, and dilution.
- [`bank_ddm.py`](../../finance-agent-core/src/agents/fundamental/capabilities/core_valuation/domain/engine/graphs/bank_ddm.py) derives risk-weighted assets as `net_income / rwa_intensity`. This is a simplified assumption. A bank model must use reported regulatory capital and risk-weighted asset facts or abstain.
- [`reit_ffo.py`](../../finance-agent-core/src/agents/fundamental/capabilities/core_valuation/domain/engine/graphs/reit_ffo.py) values a REIT as `AFFO * FFO multiple`. A released REIT path needs property-level or portfolio-level NAV, debt, lease, occupancy, and maintenance-capex coverage, or it must state that the result is a limited multiple estimate.
- [`model_selection.py`](../../finance-agent-core/src/agents/fundamental/capabilities/model_selection/domain/model_selection.py) ranks candidates and has a fallback to `dcf_standard` when no candidates are generated. The target replaces silent fallback with explicit `abstain` or a versioned, justified fallback policy.
- [`dataset_builder_service.py`](../../finance-agent-core/src/agents/fundamental/capabilities/forward_signals/domain/calibration/dataset_builder_service.py) uses analyst target prices as an anchor. [`fitting_service.py`](../../finance-agent-core/src/agents/fundamental/capabilities/forward_signals/domain/calibration/fitting_service.py) fits a mapping from those observations. This can calibrate a consensus-relative signal, but it cannot calibrate intrinsic value ground truth.
- [`valuation_flow.py`](../../finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/valuation_flow.py) is highly coupled. The target separates data preparation, model applicability, parameter policy, calculation, uncertainty, and report assembly behind typed contracts.

These findings describe the current implementation baseline. They do not waive the release gates in this document.

## 5. Single-source governance

This file owns:

- domain terms and status enums;
- public-source priority and point-in-time rules;
- canonical fact, provenance, model, valuation, calibration, and release contracts;
- model applicability and abstention requirements;
- quality severity and release-gate rules;
- the ordered service-build phases, cutover criteria, and acceptance criteria.

Operational runbooks may contain commands, environment variables, and incident procedures. They must link back to this file and must not restate policy in a way that can drift. Research notes may preserve evidence about a decision, but they are non-normative.

Every change to this target state must include:

1. the changed contract or rule;
2. the reason and affected artifacts;
3. a version bump for the relevant schema, policy, or model;
4. updated golden fixtures or an explicit design decision record;
5. the verification result for the affected release gates.

## 6. Target architecture

The target architecture is a vertical pipeline with explicit ownership, split into a persistent data plane and a stateless compute plane. Each layer emits a typed artifact and a quality report.

```text
identity resolution
    -> source acquisition and immutable snapshot
    -> filing and taxonomy parsing
    -> point-in-time canonical facts
    -> accounting normalization and quality evaluation
    -> forecast and assumption policy
    -> model applicability and selection
    -> deterministic valuation graph
    -> scenarios, sensitivity, and uncertainty
    -> calibration and out-of-sample validation
    -> provenance graph and report
```

The service keeps public financial evidence, canonical facts, taxonomy and mapping releases, model specifications, and policy releases as immutable or versioned data. The calculation plane reads those records and executes a complete request without creating a valuation session, workflow row, approval state, or server-owned job. A content-addressed response cache may be used as an optimization, but it is never the source of truth and a cache miss has exactly the same semantics as a cache hit.

| Layer | Owns | Must not own |
| --- | --- | --- |
| Identity | issuer, security, exchange, class, currency resolution | valuation assumptions |
| Source acquisition | HTTP, rate limits, cache, raw bytes, source metadata | semantic interpretation |
| Filing parser | XBRL facts, contexts, units, dimensions, taxonomy | model selection |
| Canonical facts | normalized accounting facts and point-in-time selection | narrative reasoning |
| Quality | validation issues, severity, freshness, contradiction checks | changing a number silently |
| Forecast policy | explicit forecast inputs and assumption provenance | fetching unrecorded values |
| Model selection | applicability, candidate ranking, abstention | executing formulas |
| Calculation engine | pure deterministic graphs and invariants | LLM calls, web search, hidden defaults |
| Uncertainty | scenario distributions, sensitivity, interval construction | changing the base value without trace |
| Calibration | labels, splits, metrics, artifact promotion | fitting against future information |
| Report and provenance | trace graph, status, evidence, reproducibility manifest | inventing missing evidence |

Agents call these capabilities through interfaces. They may propose a value, but the boundary service must reject a value that lacks its required provenance or quality state.

### 6.1 V1 implementation baseline

The first service release uses the repository's existing backend conventions: Python 3.11 or later, FastAPI, Pydantic v2, `httpx`, and asynchronous SQLAlchemy with PostgreSQL. The service has its own database, database role, schema namespace, migrations, cache keys, and artifact records. It must not share tables with `finance-agent-core`.

PostgreSQL stores canonical metadata, mapping decisions, model and policy releases, source-snapshot manifests, release manifests, and content hashes. V1 stores immutable raw source bytes and large artifacts in a service-owned content-addressed filesystem volume. The storage port uses `(sha256, media_type)` as the object key, verifies the hash on read, and records the volume in the release manifest. A later object store adapter may replace the volume without changing a contract. The service must not require a paid object store for local or first-release operation. It must not store per-request valuation operation state or run a service-owned valuation queue.

The calculation process is stateless per request: it receives an immutable `data_snapshot_id`, a model, explicit assumptions and uncertainty specification, and returns a result or a stable refusal before the request ends. Long-running or batched work is caller-owned orchestration. If a future deployment needs asynchronous execution, it must introduce a separately versioned computation contract without changing the deterministic calculation semantics; it must not reintroduce a hidden approval workflow.

The service exposes `GET /livez` for process liveness and `GET /readyz` for dependency readiness. Readiness requires the service schema, content-addressed store, and required signing configuration to be usable. Readiness returns only the shared `internal.v1` status shape and never exposes provider, database, or credential details.

`fundamental-json-v1` is the canonical artifact serialization. It uses UTF-8 JSON with sorted object keys, no insignificant whitespace, UTC RFC 3339 timestamps, decimal values as canonical base-10 strings, explicit `null` only where the schema permits it, and arrays sorted by their declared identity when they represent sets. It rejects JSON NaN and Infinity. SHA-256 over these bytes produces every input, calculation artifact, and release digest. The implementation must use one shared serializer for hashing, response caching, storage, and replay.

## 7. Free public data policy

The source hierarchy is part of the contract.

### 7.1 Primary accounting sources

- [SEC EDGAR APIs](https://www.sec.gov/edgar/sec-api-documentation) and the [SEC Company Facts example endpoint](https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json) provide filings, accession numbers, filing dates, and company facts for U.S. issuers.
- [XBRL specifications](https://specifications.xbrl.org/) define facts, contexts, units, dimensions, taxonomy references, and calculation relationships.
- [Arelle](https://arelle.org/) is the parser and validation runtime for filing packages. The runtime version, taxonomy package, validation profile, and plugin versions are part of the artifact.
- Filing HTML, inline XBRL, and filing exhibits remain available as raw evidence. A normalized fact cannot replace the original source bytes.

### 7.2 Official macro and sector sources

- [FRED](https://fred.stlouisfed.org/docs/api/fred/) and [ALFRED vintages](https://fred.stlouisfed.org/docs/api/fred/alfred_api.html) provide macro series and revision-aware historical observations.
- [U.S. Treasury rates](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics) provide official yield-curve observations.
- [Federal Reserve data](https://www.federalreserve.gov/data.htm), [BEA](https://www.bea.gov/open-data), and [BLS](https://www.bls.gov/developers/home.htm) provide official macro, national-account, and labor data.
- [FDIC BankFind](https://banks.data.fdic.gov/) provides public bank data for reconciliation and bank-specific cohorts.
- [Damodaran public data](https://pages.stern.nyu.edu/~adamodar/) can provide reference assumptions, but it is a reference source rather than issuer-specific ground truth.

### 7.3 Official sector sources

- **Banks.** Use SEC filings and public [FDIC BankFind](https://banks.data.fdic.gov/) or [FFIEC Call Report data](https://www.ffiec.gov/npw/FinancialReport/FinancialDataDownload) for reported regulatory and operating facts. Use the [Basel Framework](https://www.bis.org/basel_framework/) to check capital and risk-weighted asset definitions. Basel rules are not a substitute for the issuer's reported values or the applicable U.S. rule.
- **Insurers.** Use the insurer's statutory filing and applicable [NAIC risk-based capital guidance](https://content.naic.org/insurance-topics/risk-based-capital). RBC is a regulatory solvency measure, not equity value. Data availability and reuse terms vary by jurisdiction. Do not claim full coverage where the underlying statements are not openly available.
- **REITs.** Use issuer filings and [Nareit's FFO definition](https://www.reit.com/glossary/funds-operations-ffo) to check FFO. Nareit states that AFFO has no standardized definition, so preserve the issuer's reconciliation and do not compare unreconciled AFFO values as if they shared one definition. See [Nareit's AFFO glossary](https://www.reit.com/glossary/adjusted-funds-operations-affo).
- **Regulated utilities.** Use [FERC industry forms and data](https://www.ferc.gov/industries-data/data-forms), applicable [FERC electric regulations](https://www.ecfr.gov/current/title-18/chapter-I/subchapter-B/part-35), and the relevant state public utility commission's orders. Rate base, allowed returns, recovery timing, and prudence rules vary by jurisdiction. A single U.S. rate-base assumption is not valid for every utility.
- **Biotech.** Use FDA materials for [clinical research phases](https://www.fda.gov/patients/drug-development-process/step-3-clinical-research), [Drugs@FDA](https://www.accessdata.fda.gov/scripts/cder/daf/), and the [ClinicalTrials.gov API](https://clinicaltrials.gov/data-api/api) for public trial status and dates. These sources do not supply issuer-specific commercial forecasts or probabilities of success. Record those as explicit assumptions with a dated prior and validation cohort.
- **Cyclical industries.** Use the [EIA Open Data API](https://www.eia.gov/opendata/documentation.php), [USGS mineral commodity statistics](https://www.usgs.gov/centers/national-minerals-information-center/commodity-statistics-and-information), and [USDA NASS Quick Stats](https://quickstats.nass.usda.gov/api) for public commodity and industry observations. These sources validate market or sector series, not an issuer's realized price, volume, cost, or utilization.
- **SaaS and other growth companies.** Use issuer filings as the primary source for retention, customer counts, and operating efficiency when disclosed. These metrics do not have complete, uniform public coverage. Do not infer undisclosed cohort data from a peer or vendor page and label it verified.

Public access does not grant unrestricted reuse. Before adding a source, record its terms, rate limits, retention restrictions, and commercial-use conditions. If a required sector input lacks a lawful, reliable free source, the service marks that coverage unsupported or degraded. It does not replace the missing input with paid data or undocumented scraping.

### 7.4 Optional market sources

`yfinance`, public exchange pages, and scraped consensus pages may be used for market price, beta, or analyst-consensus observations only when the source terms permit it. Each observation must record provider, fetch time, URL, parser version, freshness, and warning codes. Provider failure must produce `degraded` or `abstain`; it must not silently become a verified fact. These sources never calibrate intrinsic value.

### 7.5 Acquisition rules

The acquisition layer must:

- send an identifiable User-Agent and obey provider rate limits;
- persist raw response bytes or a content-addressed equivalent;
- persist HTTP status, headers needed for freshness, URL, fetch time, and parser version;
- cache by canonical URL, query parameters, issuer, period, and source version;
- record retries, truncation, redirects, and provider errors;
- prohibit a later response from overwriting an earlier snapshot;
- expose a source health report and stop promoting a provider after repeated schema or freshness failures.

## 8. Point-in-time canonical fact layer

The canonical layer is the boundary between raw public data and valuation logic. It must be append-only for historical snapshots. Corrections create a new version rather than mutating a prior valuation input.

### 8.1 Required timestamps

Every fact and derived observation carries:

- `as_of`: the economic period or date the value describes;
- `available_at`: the earliest time the system may use it;
- `filed_at`: the source filing timestamp when applicable;
- `captured_at`: when the system fetched it;
- `accession_number` and filing version when applicable;
- `source_url` and content hash;
- `taxonomy_version`, parser version, and policy version;
- `point_in_time_policy`: the rule that selected this version.

For a historical valuation, `available_at` must be less than or equal to the valuation timestamp. For SEC filings, derive `filed_at` from the SEC acceptance timestamp and convert it to UTC. For other sources, use the publisher's release timestamp. `captured_at` never makes a later-published value available earlier. The source snapshot must preserve filing identity and amendment relationships, including `filing_version`, `is_amendment`, `amends_accession`, `supersedes_accession`, `publication_at`, and an amendment-scope classification.

Point-in-time selection is fact-level, not period-level. Build the fact key from issuer, canonical concept, period type and dates, unit, currency, sorted dimensions, consolidation scope, and security class. Exclude candidates published after the valuation timestamp. Within one filing, select the candidate with the greatest XBRL `decimals` precision. If equally precise candidates with the same fact key disagree, return `FACT_CONFLICT`. Across filings, select the latest eligible fact by `available_at`; an amendment supersedes only fact keys it re-reports or explicitly changes. A later comparative fact is eligible only from the later filing's publication time. An amendment that changes unrelated disclosure must not rewrite historical financial facts. Preserve every candidate and the selection decision for replay.

### 8.2 Canonical fact contract

The implementation may use Pydantic, dataclasses, or another typed representation, but it must provide the following fields:

```python
class CanonicalFact:
    fact_id: str
    issuer_id: str
    security_id: str | None
    concept: str
    normalized_field: str
    value: Decimal | str | bool | None
    unit: str
    scale: int
    period_start: date | None
    period_end: date
    instant: date | None
    dimensions: tuple[Dimension, ...]
    as_of: datetime
    available_at: datetime
    filed_at: datetime | None
    accession_number: str | None
    taxonomy_version: str
    source: Provenance
    quality: QualityStatus
```

The canonical layer must keep both the original XBRL concept and the normalized field. A normalized `revenue` value without the original concept, context, and unit is not auditable.

The XBRL portion of the contract must also provide a structured `XbrlContextV1` containing the full concept QName, period type (`instant` or `duration`), start and end dates or instant, unit QName and measure, dimensions with explicit members, consolidation and entity scope, and the source context identifier. Retain duplicate candidates with their validation outcome and selection reason. Never collapse facts by period end alone.

The canonical fact contract belongs to the new Fundamental service. It is not a reason to rewrite the existing Fundamental agent. The service owns the source and fact boundary:

```text
raw filing snapshot -> CanonicalFactV1 -> service-owned valuation input
existing agent -> service client -> service-owned valuation response
```

The service must not read raw `FinancialReportModel` dictionaries from the existing agent. The existing agent sends an identity and valuation request, and maps the typed response into its current domain or UI DTO. The service's internal canonical facts, cache, calculation artifacts, and calibration datasets remain service-owned.

### 8.3 Normalization rules

- Use `Decimal` for all monetary values, rates, share counts, discount factors, and intermediate results. Do not convert valuation inputs or outputs to binary floating point.
- Store currency and scale explicitly. Never infer millions or billions from a label.
- Store period type, duration, and instant separately. Do not combine quarterly and annual facts by matching dates alone.
- Resolve dimensions such as segment, geography, class of stock, and continuing operations before aggregation.
- Prefer issuer extension concepts when they are anchored to a standard concept. Record the anchor, mapping rule, and mapping confidence. An unanchored or low-confidence mapping for a valuation-critical input cannot feed a `verified` intrinsic-value artifact; it may feed a separately labelled `provisional` path only when the model policy permits it.
- Treat negative expenses, contra accounts, and sign inversions as explicit policy decisions.
- Do not coerce a missing value to zero. Use `missing`, `not_applicable`, or `unsupported`.
- Use a declared selection policy for duplicate facts. The policy must explain why a fact was preferred and must retain rejected candidates and the reason code.

## 9. Provenance and quality contracts

### 9.1 Traceable fields

Every valuation input and output is a `TraceableField`. The provenance variant tells the reviewer whether the value came from a filing, a computation, or an explicit assumption.

```python
class XBRLProvenance:
    source_url: str
    accession_number: str
    concept: str
    context_id: str
    period: str
    unit: str
    filed_at: datetime
    content_hash: str
    parser_version: str

class ComputedProvenance:
    expression: str
    inputs: tuple[str, ...]
    code_version: str
    policy_version: str

class ManualProvenance:
    description: str
    author: str
    modified_at: datetime
    review_status: str
    evidence_links: tuple[str, ...]
    automatic_value_ref: str
    automatic_provenance_ref: str
```

`ManualProvenance` is for a human or an approved assumption policy. It is not a way to hide an agent guess.

The current [`src/shared/artifacts/traceable.py`](../../finance-agent-core/src/shared/artifacts/traceable.py) type is part of the existing agent and does not satisfy the enterprise provenance contract because its XBRL provenance does not require source URL, accession, content hash, filing time, unit, or taxonomy version. The new service must define and own its enterprise provenance envelope. The service client maps only the response summary and artifact references into the existing agent. It must not share the old trace type as an internal service dependency.

### 9.2 Quality status

The quality status is separate from the numeric value. A value can be present and still be unusable.

```text
verified     source, time, unit, accounting meaning, and validation checks pass
provisional  source is acceptable but coverage or validation is incomplete
degraded     a fallback or stale provider was used; result is visible and limited
unsupported  the requested field or model is outside the supported domain
abstain      evidence is insufficient or a blocking rule fired
error        acquisition, parsing, or calculation failed
```

### 9.3 Severity model

| Severity | Meaning | Required behavior |
| --- | --- | --- |
| `block` | The input can change issuer identity, units, periods, capital structure, or formula validity. | Stop the affected valuation path. Emit a machine-readable code. |
| `warn` | The result remains usable but a reviewer must see a material limitation. | Keep the value with a warning and lower confidence. |
| `degraded` | A fallback, stale, incomplete, or non-primary source was used. | Mark the artifact degraded. Do not call it verified. |
| `abstain` | No defensible result can be produced under the selected model. | Return no intrinsic value. Return the reason and the next required evidence. |

Severity is not a log level. A `warn` may still fail a release profile when its cohort rate exceeds a threshold.

## 10. XBRL and accounting validation

The parser pipeline must run Arelle against the complete filing package, including inline XBRL, taxonomy references, linkbases, issuer extensions, and relevant exhibits.

The validation result must include:

- Arelle version and runtime isolation mode;
- taxonomy package identifiers and hashes;
- validation profile and plugin versions;
- EFM and DQC issue code, source, severity, message, field key, and blocking flag;
- calculation-linkbase inconsistencies;
- duplicate facts and conflicting contexts;
- unsupported custom concepts and mapping confidence;
- parser latency, cache hit, and lock-wait metrics;
- a deterministic validation-rule signature.

Fatal or valuation-impacting EFM and DQC issues are `block`. Non-critical issues are `warn` unless the release profile promotes them. The same normalized issue schema must feed diagnostics, replay, cohort reports, and release gates.

The accounting layer must reconcile at least these relationships where the filing provides the facts:

- assets = liabilities + equity;
- beginning cash + operating, investing, and financing cash flows = ending cash, with FX treatment recorded;
- beginning and ending debt, equity, and share counts reconcile to reported movements;
- revenue, cost, operating income, and taxes reconcile to the selected statement period;
- diluted shares reconcile to basic shares, options, restricted units, convertibles, and other dilutive instruments;
- segment totals reconcile to consolidated totals when the filing reports a complete segment set.

An unreconciled relationship is not automatically a failure. The artifact must state whether the difference is a known presentation issue, an extension mapping issue, a unit mismatch, a rounding tolerance, or an unresolved block.

## 11. Model applicability and selection

Model selection is a contract evaluation problem, not a score-only ranking problem.

The service starts with `ModelSpecV1`. `ModelSpecV2` is not part of this design. The new service has no deployed model schema to preserve, so it starts at version 1 with the complete target contract. Increment `schema_version` only for a breaking contract change. Increment `model_version` when a formula, assumption policy, eligibility rule, or supported cohort changes.

Every `ModelSpecV1` must define these fields before the model enters the registry:

| Field group | Required definition |
| --- | --- |
| Identity and ownership | stable `model_id`, `schema_version`, `model_version`, lifecycle state, model owner, accounting reviewer, independent validator, approval date, review date, and retirement trigger |
| Economic purpose | valuation question, economic mechanism, supported issuer archetypes, jurisdictions, accounting bases, valuation basis (`enterprise`, `equity`, or `asset`), and permitted report label |
| Input contract | canonical fact IDs, semantic definitions, types, units, currency, period, dimensions, minimum history, `available_at` rule, source hierarchy, minimum quality state, and acceptable proxies for every input |
| Assumption contract | each forecast and parameter, method, source or derivation, permitted bounds, scenario treatment, convergence rule, terminal policy, and explicit statement that no hidden default is allowed |
| Formula graph | named calculation nodes, equations, dependency edges, sign conventions, tax treatment, discount timing, capital bridge, and formula version |
| Numerical policy | arithmetic type, precision, rounding boundary, absolute and relative tolerance, invalid denominator rules, non-finite handling, and currency conversion policy |
| Eligibility policy | required inputs, minimum quality, acceptable ranges, cross-field invariants, industry and capital-structure rules, forbidden conditions, and deterministic rejection codes |
| Abstention policy | blocking conditions, degraded-but-usable conditions, missing-evidence response, and the precise conditions that prevent an intrinsic-value result |
| Uncertainty policy | scenario variables, distributions or bounds, dependency assumptions, interval method, supported horizon, and whether interval coverage has been empirically validated |
| Calibration contract | forecast target and label source, point-in-time label rule, cohort definition, split manifest, baseline, metrics, sample threshold, promotion rule, and expiry rule |
| Validation evidence | golden cases, independent challenger, node-level expected values, property tests, known limitations, and latest validation report reference |
| Reproducibility | source, schema, taxonomy, parser, policy, calculation, and calibration versions needed to replay the model |

Do not make fields optional merely because the first implementation has no value for them. Use a typed `not_applicable` reason for an inapplicable field, a typed `unknown` state for missing evidence, and a versioned policy for any proxy. The registry must reject a model definition that omits a required group.

The selection result must include all candidates, rejected candidates, missing fields, forbidden conditions, quality statuses, score components, selected model, and abstention reason when no candidate passes.

The selector must not choose a model solely because its score is highest. A candidate that violates a required input or forbidden condition is ineligible. If no candidate is eligible, return `abstain`.

### 11.1 Coverage matrix

| Company type | Primary model family | Required evidence | Models that are limited or forbidden |
| --- | --- | --- | --- |
| Mature non-financial | FCFF DCF, EVA cross-formulation, EV-based cross-check | multi-year revenue, EBIT, tax, D&A, capex, working capital, debt, cash, shares | terminal-value-only result without a stable cash-flow history |
| High-growth or SaaS | unit-economics forecast plus FCFF or revenue-to-margin transition | a declared forecast path backed by issuer facts or an approved dated assumption policy; gross margin, SBC, dilution, cash runway, and path to operating margin; retention or cohort evidence when that driver is used | mature-margin DCF without a transition path; a `verified` result when a material transition or dilution input is unknown |
| Bank | excess-return or dividend model using regulatory capital | RWA, CET1 or equivalent, payout, book value, asset quality, net interest and provision data | FCFF, enterprise-value bridge, synthetic RWA from net income |
| Insurance | statutory excess-return or dividend model | statutory capital, book value, reserve development, underwriting result, investment income, and legal-entity structure | FCFF without a justified debt and operating separation; an embedded-value cross-check requires an issuer-published, auditable actuarial bridge |
| REIT | NAV plus AFFO or dividend cross-check | property value, occupancy, rent, debt maturity, interest cost, maintenance capex, shares | AFFO multiple presented as full NAV valuation |
| Utility | regulated-asset or FCFF model | rate base, allowed return, capex plan, debt, regulatory jurisdiction, tariff data | high-growth SaaS assumptions |
| Cyclical | normalized earnings, mid-cycle FCFF, and scenario range | cycle history, utilization, price-volume drivers, replacement capex, balance-sheet stress | one-year peak or trough DCF as base case |
| Biotech | probability-adjusted pipeline value plus cash runway | trial phase, indication, probability assumptions, milestone timing, dilution, cash burn | revenue multiple before a defensible commercial path |
| Conglomerate or holding company | segment sum-of-the-parts | segment statements, ownership, holding-company debt, taxes, cross-holdings, discount policy | consolidated DCF that hides segment economics |

The matrix defines the minimum target coverage. A model may produce a provisional estimate for a narrower case, but the report must state the limitation and quality status.

### 11.2 Valuation model definitions

The service uses one model-definition format for every family. A model family is not supported just because the registry contains its ID. It becomes eligible only after its required evidence, formula graph, abstention rules, independent checks, and golden cohort pass the release gates.

| Model ID | Economic method and output | Minimum issuer-specific evidence | Reject or abstain when |
| --- | --- | --- | --- |
| `fcff_dcf` | Discount operating free cash flow at WACC, then bridge enterprise value to equity value. | Multi-year revenue, operating profit, taxes, D&A, capex, working capital, debt, cash, leases, share scope, and cost-of-capital inputs. | The business lacks a defensible operating forecast, terminal value dominates without a stable convergence case, or the capital bridge cannot reconcile. |
| `transition_fcff_dcf` | Forecast explicit growth and margin transition before applying a mature-state terminal policy. SaaS is an issuer archetype under this model, not a separate formula. | Filed revenue history and gross margin, SBC, dilution, cash runway, and a supported path to normalized margins. Require retention, cohort, or acquisition-efficiency evidence whenever the forecast uses that driver. | Growth or margin convergence is guessed, a peer or vendor substitutes for an undisclosed issuer fact, material dilution is omitted, or the company has no supportable path to positive unit economics. |
| `residual_income` | Value equity as current book equity plus discounted residual income: net income less the required return on beginning book equity. | Reliable book value, earnings, cost of equity, distributions, and a clean-surplus or documented book-value bridge. | Book value is economically meaningless, earnings and book-value movements cannot reconcile, or continuing residual income has no justified convergence policy. |
| `eva` | Value invested capital plus discounted economic profit: NOPAT less a capital charge on invested capital. Under consistent forecasts, this is a cross-formulation of DCF. | Invested capital, NOPAT, WACC, and documented operating adjustments such as research capitalization or lease treatment. | Adjustments are unsupported, invested capital is incomplete, or EVA and DCF disagree beyond declared tolerance without an explained policy difference. |
| `dividend_discount` | Discount expected shareholder distributions at cost of equity. | Sustainable distributable earnings, capital requirements, payout policy, diluted shares, and a justified terminal payout or growth policy. | Dividends are temporarily funded by asset sales or unsustainable capital depletion, or the model confuses enterprise and equity cash flows. |
| `bank_excess_return` | Value bank equity from book value and excess returns over the required return, with regulatory capital and payout constraints. | Reported RWA, CET1 and other required capital ratios, tangible and reported book value, charge-offs, provisions, net interest income, deposits, and payout history. | Required regulatory facts are missing, synthetic RWA is used, asset quality is unresolved, or projected capital breaches a declared constraint. |
| `insurance_statutory_excess_return` | Value insurer equity from statutory surplus and sustainable excess returns or distributable capital. | Jurisdiction-specific statutory statements, capital and RBC data where applicable, reserve development, underwriting results, investment income, and legal-entity structure. | Reserve adequacy or legal-entity capital cannot be assessed, statutory and GAAP figures are mixed without a bridge, or the model treats RBC as market value. |
| `reit_nav` | Estimate property-level or portfolio NAV from operating income and market cap-rate assumptions, then reconcile debt and equity claims. Use FFO or AFFO only as a cross-check. | Property or portfolio NOI, occupancy, lease terms, cap-rate evidence, debt and maturities, preferred claims, recurring capital expenditure, and diluted shares. | Property coverage is incomplete, valuation assumptions lack a dated source, or AFFO is presented as standardized when the issuer's reconciliation is unavailable. |
| `regulated_utility` | Forecast jurisdiction-specific regulated cash flows. Use rate base, allowed return, approved tariffs, and capital plans to constrain operating forecasts. | Regulator orders, rate-base balances, allowed ROE, approved recovery mechanisms, jurisdiction, capex, debt, and disallowance risk. | Jurisdictional data is unavailable, rate base is treated as equity value, or unapproved projects and returns are included as certain. |
| `normalized_cyclical` | Estimate mid-cycle earnings or cash flows across a full relevant cycle, then report stress and recovery scenarios. | Cycle history, commodity or price-volume drivers, capacity, utilization, replacement capex, working-capital swings, and balance-sheet obligations. | Only peak or trough earnings are available, the cycle regime changed without a new model policy, or liquidity risk is omitted. |
| `biotech_rnpv` | Sum probability-adjusted, time-discounted cash flows for each pipeline asset and reconcile corporate cash burn, milestones, and dilution. | Trial and indication identity, public trial status, development stage, milestone timing, explicit probability priors, commercial assumptions, patent or exclusivity period, cash runway, and share dilution. | Trial identity or stage is uncertain, probability assumptions are hidden, commercial cash flows lack a dated basis, or funding and dilution are not modeled. |
| `sum_of_parts` | Value each business segment with a justified method, then reconcile holding-company debt, taxes, cross-holdings, minority claims, and any holding discount. | Segment financials, ownership, segment debt and cash, capital allocation, eliminations, tax basis, and a declared method for each segment. | Material segments are unvalued, consolidated eliminations are duplicated, or a holding discount is applied without an explicit policy. |
| `relative_multiple_check` | Compare the issuer with a point-in-time peer set using EV/EBITDA, EV/revenue, P/E, or sector-specific multiples. This is a market-relative check, not intrinsic-value ground truth. | Peer identity and date, comparable accounting definitions, capital structure, leases, growth, margins, and outlier policy. | The peer set is selected after seeing the desired output, periods or accounting bases differ without normalization, or the result is labeled intrinsic value. |

`dcf_standard` maps to `fcff_dcf` only after its formula and capital bridge satisfy this definition. `dcf_growth` and `saas` map to `transition_fcff_dcf` only when the transition evidence exists. `ev_revenue`, `ev_ebitda`, and ordinary P/E are cross-checks. The service does not preserve old IDs as aliases unless an explicit mapping is recorded in a versioned registry change.

Do not average model outputs into an ensemble by default. Show model disagreement as a diagnostic. Add an ensemble only when the registry records its economic rationale, combination method, calibration cohort, independent challenger, and abstention behavior.

## 12. Forecast and assumption policy

Forecasts are first-class data. They are not anonymous fields in a model payload.

Each assumption records:

- metric, unit, period, and scenario;
- raw source facts and source observations;
- transformation formula;
- prior, peer, or macro reference if used;
- lower and upper bounds;
- convergence rule and terminal policy;
- whether it is sourced, computed, manual, or calibrated;
- owner, policy version, and review status;
- sensitivity weight and uncertainty distribution.

The policy must separate `raw`, `guarded`, and `calibrated` values. The report shows all three when they differ. A guardrail changes a value only through a named policy with a reason code. A calibration mapping never overwrites the raw observation.

Terminal growth must remain below the applicable discount rate by a declared margin and must respect the selected macro or industry ceiling. A terminal growth value that lacks a point-in-time macro reference is provisional or abstained.

## 13. Deterministic valuation engine

The engine is a versioned DAG of pure functions. It accepts a typed `ValuationInput` and returns a typed `CalculationArtifact` with no network, file, LLM, or clock access.

The new service owns its calculation engine and model registry. It may reuse reviewed pure mathematical ideas from [`CalculationGraph`](../../finance-agent-core/src/agents/fundamental/capabilities/core_valuation/domain/engine/core.py), but it must not import the existing agent's application, workflow, or private domain modules at runtime. The new engine has typed inputs, typed outputs, independent formula fixtures, and its own release version. The existing graph is evidence for current behavior, not an internal dependency of the new service.

### 13.1 Common calculation rules

- Use explicit currency, scale, unit, and sign conventions at every node.
- Reject mixed currencies and mixed share scopes.
- Reject zero or negative share counts, invalid discount denominators, and non-finite values.
- Record whether debt is gross or net, whether leases are included, and whether preferred stock and non-controlling interests are deducted.
- Keep equity value and enterprise value distinct. The bridge must show cash, debt, preferred stock, lease liabilities, minority interest, and other adjustments separately.
- Use diluted weighted-average shares for per-share earnings and an as-of diluted share count for equity value. Do not mix the two without a policy record.
- Represent each capital-bridge input as `present`, `confirmed_absent`, `unknown`, or `unsupported`, with source and policy provenance. Any `unknown` in debt, cash, preferred stock, lease liabilities, non-controlling interests, dilutive instruments, or share scope blocks an intrinsic-value calculation. V1 has no materiality threshold that turns an unknown claim into zero. A model may return `provisional` or `degraded` only for a declared non-blocking limitation; otherwise it abstains.
- Make mid-year versus end-year discounting explicit.
- Store monetary inputs and outputs as typed decimal amounts with an explicit currency and scale. Binary floating point is forbidden in the V1 calculation path.
- Record all rounding only at presentation boundaries. Never round intermediate values.

The alternative intrinsic-value formulations must use consistent cash flows, capital charges, and discount rates:

```text
Residual income_t = Net income_t - Cost of equity * Beginning book equity_t
Equity value = Current book equity + PV(forecast residual income) + PV(continuing residual income)

EVA_t = NOPAT_t - WACC * Beginning invested capital_t
Enterprise value = Current invested capital + PV(forecast EVA) + PV(continuing EVA)

Equity value under DDM = PV(forecast shareholder distributions) + PV(continuing distributions)
```

These formulations provide independent calculation paths only when their input and accounting policies are independently reconciled. They are not independent if they reuse the same unreviewed forecast or capital assumptions.

### 13.2 FCFF and WACC

The V1 FCFF policy is:

```text
NOPAT_t = EBIT_t - forecast cash taxes_t
FCFF_t = NOPAT_t + D&A_t - total capex_t - change in operating working capital_t
TV_5 = normalized FCFF_6 / (WACC - terminal_growth)
Enterprise value = sum(FCFF_t / (1 + WACC)^t for t=1..5) + TV_5 / (1 + WACC)^5
Equity value = enterprise value + cash + non-operating assets - gross debt - finance lease liabilities - preferred claims - non-controlling interests - other senior claims
Intrinsic value per share = common equity value / as-of diluted common shares
```

V1 uses end-of-year discounting. `change in operating working capital_t` is current-period operating net working capital minus the prior period. The terminal period is a normalized sixth year, not a copy of year five. The model records the terminal-year margin, reinvestment, and return-on-invested-capital assumptions that produce `FCFF_6`.

The WACC policy must identify debt and equity weights, cost of debt, tax treatment, risk-free tenor, beta source and window, market risk premium source and vintage, country risk treatment, and any company-specific adjustment. A CAPM cost of equity is not a complete WACC by itself.

### 13.3 SBC and dilution

SBC policy must choose one internally consistent treatment:

- treat SBC as an operating expense and model the resulting cash flow;
- add back SBC only when the model also includes the expected dilution or repurchase cost;
- or abstain when the filing does not provide enough information to avoid double counting.

For `us-gaap-public-v1`, keep SBC as an operating expense in every forecast year and set `sbc_add_back = 0`. Use an as-of diluted share count that starts with point-in-time common shares outstanding and adds existing dilutive awards under the treasury-stock method at the selected valuation-date quote. Do not add forecast dilution for future SBC grants because the forecast already charges their compensation expense to FCFF. Model future share-count changes only for separately identified non-SBC issuance, conversion, or repurchase events. If award data, the valuation-date quote, or the resulting share scope is unknown, abstain. The artifact records SBC expense, the zero add-back, award dilution, any non-SBC share changes, basic shares, diluted shares, and the selected share scope.

### 13.4 Bank and insurance models

Bank models use regulatory capital, reported RWA, book value, payout, and return-on-equity or excess-return relationships. They must not infer RWA from net income alone. Forecast capital must satisfy the model's declared regulatory and management buffers. Use a dividend model only when projected distributions remain compatible with those constraints.

Insurance models begin with statutory surplus and legal-entity structure. They separate reserve development, underwriting result, investment income, unrealized gains, reinsurance, and shareholder distributions. Reconcile statutory values to GAAP before using either basis. An RBC ratio constrains solvency and distributions; it is not an equity multiple or an asset value.

### 13.5 REIT and property models

REIT valuation estimates each material property or portfolio component from stabilized net operating income and an explicit cap-rate assumption, then subtracts debt, preferred claims, and other liabilities. It reconciles occupancy, lease expiry, rent growth, tenant improvements, maintenance capital, debt maturities, and diluted shares. FFO follows the Nareit definition. AFFO is not standardized. Use it only after preserving the issuer's reconciliation. If public evidence cannot support property-level cap rates or operating assumptions, report a provisional estimate or abstain.

### 13.6 Cyclical and pipeline models

Cyclical models normalize commodity prices, utilization, margins, and reinvestment across a full relevant cycle. They report peak, trough, and mid-cycle scenarios and test liquidity at the trough. A regime change requires a new model version and cohort.

Biotech models value each asset with probability-adjusted, time-discounted milestones and commercial cash flows. The model states the development-stage prior, event date, indication, trial design, timing, commercial assumptions, exclusivity period, funding needs, and dilution. FDA and ClinicalTrials.gov records validate public trial facts. They do not supply a company's probability of success or market size. A missing, undocumented probability policy forces `provisional` or `abstain`.

### 13.7 Regulated utilities

Utility models use jurisdiction-specific rate-base balances, allowed returns, approved tariffs, recovery timing, capital plans, and disallowance risk to forecast shareholder cash flows. A rate base is not equity value. Model each regulator and material rate mechanism separately. Reconcile the resulting cash flows to debt, preferred claims, and shares.

### 13.8 Sum-of-the-parts and relative multiples

SOTP calculations keep each segment valuation, net debt allocation, holding-company discount, tax leakage, cross-holdings, and non-controlling interest as separate traceable nodes. The consolidated result cannot hide an unvalued segment.

Relative multiples use a peer set fixed at the valuation timestamp. The model records peer selection rules, accounting normalization, leases, growth, margins, and exclusions. Multiples remain a cross-check against market pricing. They do not become intrinsic-value labels or calibration targets.

## 14. Scenarios, sensitivity, and uncertainty

Every released valuation contains:

- a base, downside, and upside scenario with named assumptions;
- one-way sensitivity for the dominant value drivers;
- two-way sensitivity for discount rate and terminal growth or the model's equivalent drivers;
- a distribution or interval for intrinsic value when the model has enough historical error data;
- the share of value contributed by terminal value and the top assumptions by value sensitivity;
- a deterministic random seed and distribution specification for Monte Carlo runs.

Monte Carlo is not a substitute for model validation. In the stateless API, a range alone is invalid: the caller must provide the distribution type, bounds and mode/mean where applicable, sample count, deterministic random seed, parameter dependencies or correlation specification, and the invalid-draw policy. The service validates these inputs against economic invariants and rejects them when they are incomplete, contradictory, or outside the model contract. It never silently clamps, replaces, or fills a caller-supplied range. The simulation records the joint distribution, parameter correlations, truncation rules, number of requested and valid draws, seed, sampler version, invalid-draw counts and reasons, and convergence diagnostics. If the valid sample count is below the declared minimum, the result is `abstain` or `provisional` according to the model policy rather than a fabricated interval. The report must distinguish a model-implied interval from a historically calibrated prediction interval.

Intervals must be checked for coverage, sharpness, interval score, and stability by cohort. A narrow interval that misses the realized label is worse than a wider interval with honest coverage.

## 15. Calibration and backtesting protocol

Calibration has separate targets. The system must not use one score for all of them.

### 15.1 Calibration layers

1. **Extraction calibration.** Does the parser select the right fact, unit, period, dimension, and filing version?
2. **Forecast calibration.** Do revenue growth, margin, FCF, ROE, FFO, or other forecast distributions match subsequently disclosed outcomes?
3. **Uncertainty calibration.** Do prediction intervals achieve their stated coverage on out-of-sample labels?
4. **Model-selection calibration.** Does the selected model outperform eligible alternatives on its declared cohort and horizon?
5. **Market-outcome evaluation.** Does the valuation signal predict later returns or revisions after costs and risk controls? This is an investment-signal test, not intrinsic-value truth.

The existing forward-signal mapping against analyst target prices belongs to layer 5 as a consensus-relative diagnostic. It must not be used to claim that intrinsic values have been calibrated.

### 15.2 Label construction

Use labels that are available without look-ahead:

- For accounting extraction, compare the point-in-time fact with the first subsequently published filing that reports the same economic period. Keep restatements as a separate restatement label.
- For forecasts, use the first subsequent filing or official source that discloses the realized metric. Do not replace the historical label with a later restated value in a point-in-time score.
- For uncertainty, evaluate the declared horizon and label availability time. Do not shorten the horizon after observing the outcome.
- For market-outcome evaluation, define the return window, corporate-action treatment, delisting handling, benchmark, and transaction-cost assumption before fitting.

### 15.3 Time and leakage controls

Every split is time-based. Use train, validation, and out-of-sample periods in chronological order. When forecast windows overlap, use purged cross-validation and an embargo between training and validation windows. Group observations by issuer when issuer-level leakage is possible. Keep a manifest of included and excluded rows with reasons.

### 15.4 Metrics and baselines

Forecast metrics depend on the metric type and must include a naive baseline:

- continuous values: MAE, RMSE, median absolute error, signed bias, and scaled error;
- event probabilities: Brier score, log score, calibration slope and intercept, and reliability by cohort;
- rates and ratios: bounded error, calibration by decile, and sign accuracy where useful;
- quantiles: pinball loss and empirical coverage;
- intervals: coverage, interval width, interval score, and coverage by cohort;
- model selection: eligible-model regret, selection accuracy against a fixed evaluation protocol, and abstention precision;
- market outcomes: information coefficient, rank correlation, hit rate, drawdown, turnover, and costs, with confidence intervals.

Predeclare the minimum sample and metric acceptance bounds in `ModelSpecV1`. Derive the minimum sample from the precision required for the cohort metric. Do not treat an underpowered result as a pass. Do not promote a calibration artifact unless it improves out-of-sample performance against both the raw model and the declared naive baseline, while staying within data-quality and stability limits.

### 15.5 Calibration artifact

Each promoted calibration artifact records:

```text
calibration_id and version
target layer and metric
training window and point-in-time data snapshot
feature and label contracts
split, purge, and embargo policy
model or mapping class and hyperparameters
raw versus calibrated metrics
naive baseline metrics
cohort metrics and sample counts
confidence intervals or bootstrap method
fallback and insufficient-sample policy
owner, review status, and expiry date
```

Calibration falls back to the raw policy when its minimum sample, coverage, stability, or OOS improvement gates fail. The fallback is visible in the valuation trace.

## 16. Provenance graph and reproducibility

The report must expose a directed acyclic provenance graph:

```text
raw response
  -> filing package
  -> parsed XBRL fact
  -> canonical fact
  -> normalized metric
  -> forecast or assumption
  -> model input
  -> calculation node
  -> scenario or interval
  -> reported intrinsic value
```

Every edge records the transformation expression, input IDs, output ID, code version, policy version, and quality result. Every node records source, time, unit, and status where applicable.

The reproducibility manifest must include:

- valuation request and decision timestamp;
- issuer and security identity resolution;
- immutable source snapshot IDs and content hashes;
- selected model and model version;
- canonical fact and assumption IDs;
- calculation graph version and runtime version;
- calibration artifact IDs;
- random seeds and numerical settings;
- quality issues and release-profile thresholds;
- output hash.

The replay command must accept the manifest and reproduce the calculation without network access. A replay difference must identify the first differing node and the version or input that changed.

## 17. External verification without paid data

Public primary sources and independent tests can verify specific claims. They cannot certify an intrinsic value as objectively true because intrinsic value is not directly observable.

| Claim | Independent evidence | What the evidence establishes | What it does not establish |
| --- | --- | --- | --- |
| A reported fact is correct | Issuer filing, accession, XBRL context, unit, period, dimensions, and SEC Company Facts where the concept is covered | The canonical fact matches a public source available at the decision time. | That the fact alone makes a model appropriate. |
| Filing parsing is correct | Arelle output, SEC EFM or DQC diagnostics, extension-concept review, and accounting reconciliations | The parser and mapping follow the selected taxonomy and validation rules for the tested filing. | That every custom concept has an unambiguous economic meaning. |
| A macro input is correct | Treasury, FRED or ALFRED vintage, BEA, BLS, Federal Reserve, or FDIC observation with its publication time | The recorded observation and vintage match the public source. | That a selected risk premium, beta window, or forecast is uniquely correct. |
| A sector input is correct | Basel and regulatory filings for bank capital, NAIC statutory materials for insurers, Nareit definitions for FFO, regulator orders for utilities, FDA and ClinicalTrials.gov records for trial status | The service used the declared sector definition or public event record. | That a solvency ratio, FFO measure, allowed return, or trial status is an equity valuation. |
| A formula is correct | Independent implementation with node-level expected values, dimensional checks, property tests, and mutation tests | The implementation matches the declared equations and invariants within tolerance. | That the equations and assumptions represent every issuer's economics. |
| A forecast is calibrated | First subsequently published operating facts, chronological out-of-sample evaluation, raw and naive baselines, proper scoring rules, and confidence intervals on metrics | The declared forecast target has measured out-of-sample error and interval coverage for the tested cohort. | That an intrinsic-value estimate is calibrated to a true value. |
| A result is reproducible | Immutable source snapshots, pinned versions, offline replay, and matching output hashes | The same recorded inputs and versions reproduce the same artifact. | That the input sources or model assumptions were economically sound. |
| Model governance is adequate | Independent validation, model inventory, limitations, approval, monitoring, and change history | The service followed its documented governance process. | A regulatory approval or external certification of this project. |

Required free evidence includes source reconciliation for a fixed issuer cohort, Arelle validation, point-in-time macro vintages, independent formulas, property tests, golden fixtures, offline replay, and out-of-sample reports. Store the raw source reference and the exact rule, tool, and version that produced each check.

The [Federal Reserve's SR 26-2](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm), issued April 17, 2026, replaces SR 11-7. It is interagency model-risk guidance and is expected to be most relevant to banking organizations with more than $30 billion in assets regulated by the Federal Reserve. Use it as a governance reference where relevant. It does not directly regulate or certify this service. Use the [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework) when an ML component affects a decision or confidence label. Neither reference replaces service-specific validation evidence.

Analyst targets, current prices, scraped pages, and LLM explanations may support discovery or comparison. They cannot serve as the sole verification source for an accounting fact, a forecast label, or an intrinsic-value claim.

## 18. Golden datasets and cohorts

The enterprise verification corpus must contain fixed, versioned cohorts rather than one-off ticker tests. Its broad sector list is not a gate for `us-gaap-public-v1`; the first-release cohort is defined in section 24.2 and may use explicit abstention fixtures for unsupported sectors.

Minimum cohorts:

- six large issuers covering technology, consumer, healthcare, industrial, financial, and energy or utility sectors;
- at least one extension-heavy SEC filing;
- at least one bank with regulatory capital data;
- at least one insurer;
- at least one REIT;
- at least one cyclical company;
- at least one pre-profit or pipeline company;
- at least one conglomerate or SOTP case;
- one issuer with material SBC and multiple share classes;
- one issuer with a filing restatement or amended filing. The fixture must distinguish an amendment that changes a valuation-relevant fact from an amendment that only changes unrelated disclosure; both cases exercise the fact-level amendment-scope policy.

Each case has a point-in-time input snapshot, expected facts, expected validation issues, expected model eligibility, expected calculation nodes, and expected abstention or degraded state when applicable. The dataset contains no hidden future facts.

Golden fixtures are updated only through a versioned review. A changed expected output requires a reason, a policy or formula version change, and a before-and-after report.

## 19. Release gates

An artifact or code release is blocked when any required gate fails.

### 19.1 Contract and source gates

- schema validation passes for every canonical fact, assumption, valuation, calibration, and report artifact;
- all required point-in-time fields are present;
- source hashes, accession numbers, taxonomy versions, and parser versions are present;
- replay can run from the immutable snapshot without network access;
- provider warnings and fallback codes are present in the report.

### 19.2 Accounting and calculation gates

- fatal or valuation-impacting EFM and DQC issues are zero for verified artifacts;
- accounting reconciliation is within the declared tolerance or has a named exception;
- model inputs meet the selected `ModelSpec` requirements;
- no mixed units, currencies, periods, or share scopes exist;
- formula invariants and property tests pass;
- no hidden default, silent fallback, or untraced manual override exists;
- deterministic replay output hash matches the release fixture.

### 19.3 Calibration and cohort gates

- OOS metrics beat raw and naive baselines for the declared target;
- interval coverage and error metrics meet the cohort profile;
- sample counts meet minimums by model and sector cohort;
- drift, provider fallback, missingness, and abstention rates stay below profile limits;
- the release includes the calibration artifact, split manifest, and cohort report;
- a rejected calibration remains rejected and cannot silently become active.

The fixed golden cohort is an engineering regression and replay corpus. It is not, by itself, evidence that a calibration mapping or prediction interval is reliable. Calibration and OOS cohorts are separate, chronological datasets with their own split manifest, label-availability rule, missingness report, and uncertainty estimates. Enterprise model releases must declare the evidence required for each target and cohort. The V1 profile binds that policy to the minimums in section 24.4.3. Future profiles may use a different sample policy only after recording the target, cohort rationale, and release evidence. When a cohort is too small or too sparse for a defensible estimate, calibration remains inactive and the report states that limitation.

### 19.4 Governance gates

- model, policy, parser, taxonomy, and calibration versions are pinned;
- validation-rule signature drift is reviewed;
- an independent reviewer can inspect the provenance graph and raw evidence;
- the change has a rollback or explicit data-rebuild procedure;
- the canonical specification and relevant operational runbook agree.

Model promotion requires a signed verification attestation from a trusted release
workflow. The attestation binds the model digest, release-subject digest, exact
source commit, verification-suite digest, run identity, complete gate set,
release-artifact hashes, approver, and approval and expiry timestamps. The
deployment inventory pins the verifier identity, workflow identity, Ed25519
public key, expected source commit, and expected suite digest. Missing pins,
mismatches, or an invalid signature block promotion. Keep the signing key in the
verification workflow.

The signature records which trusted workflow checked the bound inputs. It does
not replace independent reproduction of the reported evidence. Synthetic
attestations and source bytes in unit tests exercise the governance contract;
they are not model-release evidence. Keep a family unsupported until its
release evidence is complete and independently reproducible.

## 20. Versioning and change control

Version these independently:

- canonical fact schema;
- source and parser contract;
- taxonomy mapping package;
- quality-rule profile;
- model specification;
- calculation graph;
- assumption policy;
- calibration artifact;
- report schema.

A breaking change increments the relevant major version and invalidates incompatible historical artifacts. A policy change creates a new artifact version and preserves old outputs. A source correction creates a new point-in-time snapshot. Do not rewrite historical reports in place.

The release manifest must state which versions are compatible. The loader must reject an incompatible combination rather than silently coerce it.

Every release profile must pin its tolerances, blocking rule set, calibration promotion rule, cohort minimums, interval metrics, missingness limits, and drift limits before evaluation begins. Changing one of these thresholds creates a new quality-policy version and requires the affected fixtures, reports, and release decision to be rerun. A threshold is not evidence merely because a previous implementation passed it.

## 21. Ordered service-build phases

The target is large, but the dependency order is fixed. The service is built as an isolated product. Each phase produces a verifiable contract before the next phase consumes it. The existing Fundamental agent remains unchanged until the service contract passes its cutover gate; subsequent agent adaptation belongs to the agent integration layer.

### 21.1 Delivery stages

The service starts with its complete target contracts and adds supported coverage in measured releases. Runtime availability and model support are separate claims: an implemented calculator or exploratory registry entry does not make a family eligible for service advertisement or valuation.

| Stage | Scope | Exit evidence |
| --- | --- | --- |
| Documentation foundation | Canonical specification, complete `ModelSpecV1`, source register, and staged release gates. | Contract and release decisions are fixed in this specification. |
| Pragmatic service release | Deployable service with point-in-time SEC facts, replay, explicit quality states, deterministic calculations, and the limited coverage in section 24.1. | Every section 24.5 threshold passes for the declared profile. Unsupported archetypes abstain. |
| Controlled family expansion | Add one complete family at a time in this order: U.S. banks, insurers, REIT NAV, regulated utilities, cyclical issuers, biotech, SOTP, then IFRS accounting profiles. | The family has a complete `ModelSpecV1`, lawful source coverage, positive and negative golden cases, independent node checks, and a predeclared out-of-sample cohort when its forecasts are calibratable. Until then it remains explicitly unsupported. |
| Enterprise service | Governed model inventory, broader issuer and jurisdiction coverage, source health and retention controls, independent model validation, calibrated forecast intervals where data permits, operational SLOs, incident recovery, and controlled releases. | An independent reviewer can reproduce artifacts, inspect each model's validation record, confirm monitoring and rollback evidence, and verify the stated coverage limits. |

All model families use the same versioned contract from the first service release. A new family adds a registry entry and its own evidence. It does not require a new `ModelSpec` schema or a rewrite of earlier families.

"Fully tested before integration" means that every model and path advertised by the intended service release passes that release's gates. It does not mean that unsupported future families must exist before the first agent call. The first integration may expose only the pragmatic profile, with all other families returning explicit `unsupported` or `abstain` states.

1. **Freeze the canonical specification.** Register this file as the only normative Fundamental document. Mark older design documents non-authoritative and remove conflicting index entries.
2. **Create the service boundary.** Add a private internal-service contract with `internal.v1` context, `fundamental.v1` data and calculation schemas, explicit input digests, deadlines, stable errors, readiness, and correlation IDs. The contract has no service-owned approval or valuation-operation state.
3. **Build the service-owned source snapshot.** Persist raw SEC, filing-referenced DTS, selected Treasury/ALFRED/Damodaran observations, and optional market observations with content hashes, timestamps, provider metadata, legal-use references, and service-owned cache keys.
4. **Build the point-in-time fact and taxonomy registry.** Add canonical facts, accession and amendment selection, complete DTS manifests, content-addressed taxonomy packages, reviewed canonical mapping decisions, dimensions, units, and replay without network access.
5. **Harden Arelle validation.** Load pinned EFM/DQC plugins and rule packages; make taxonomy, plugin, validation-rule signatures and normalized findings first-class artifacts with block and warn gates. Do not add custom plugins in the first release.
6. **Build the service calculation boundary.** Implement the frozen `ValuationInputV1`, pure deterministic graphs, approved WACC and capital-structure policies, and explicit quality states without importing the old agent internals.
7. **Build eligibility and model selection.** Add required fields, forbidden conditions, minimum quality, and explicit abstention to the two V1 model specs: `fcff_dcf` and `transition_fcff_dcf`.
8. **Build scenarios, uncertainty, provenance, and replay.** Produce versioned artifacts with deterministic seeds, source graphs, release manifests, and offline replay.
9. **Build point-in-time calibration.** Use first subsequently published labels, chronological splits, purge, embargo, raw and naive baselines, and separate market-signal evaluation.
10. **Create golden cohorts and independent checks.** Add public-source reconciliation, independent formulas, property tests, and sector coverage.
11. **Run the service cutover gate.** Compare the new service against fixed fixtures and independently expected outputs. Only after the gate passes does the existing agent call the service in production.
12. **Expand model families.** Add banks, insurance, REIT NAV, regulated utilities, cyclical, biotech, SOTP, and IFRS profiles in the order defined in section 21.1. Keep every family behind the same service contracts.

The phases are architectural dependencies, not a promise that every phase is a small task. A phase is complete only when its service contract, fixtures, replay evidence, and release gate exist. The existing Fundamental agent requires no internal changes before the cutover gate.

## 22. Explicit unsupported and degraded behavior

The user-facing report must use these states consistently:

- `verified`: the requested model and inputs pass all required gates.
- `provisional`: a result exists, but a declared coverage or assumption limitation remains.
- `degraded`: a non-primary or stale source, provider fallback, or limited proxy affected the result.
- `unsupported`: the company archetype or requested metric is outside the implemented model coverage.
- `abstain`: the system refuses to emit an intrinsic value because evidence or invariants fail.
- `error`: the process failed before a defensible result could be produced.

An abstention report must include the blocking codes, missing evidence, selected model candidates, and the smallest next action that could make the case eligible. A degraded report must include the provider and freshness limitation. The UI and API must not convert these states into a numeric value with a generic confidence label.

## 23. Final acceptance criteria

The Fundamental service reaches the target state only when all of these statements are true:

- one canonical specification governs the domain and old documents cannot override it;
- a point-in-time replay never reads a fact that was filed later than the valuation timestamp;
- every reported number has a source or a formula trace, a unit, a period, a quality status, and a version;
- Arelle and accounting validation issues are normalized and consumed by release gates;
- model selection can abstain and explains eligibility and rejection reasons;
- the deterministic engine has no LLM or network dependency and passes independent formula checks;
- SBC, dilution, share scope, debt, cash, preferred stock, leases, and non-controlling interests follow one recorded policy;
- each supported company archetype has a complete model contract, and unsupported archetypes abstain;
- scenarios, sensitivity, and uncertainty identify dominant assumptions and report calibrated coverage where available;
- calibration uses point-in-time labels, chronological OOS evaluation, purge and embargo where required, and raw and naive baselines;
- consensus and market outcomes are kept separate from intrinsic-value ground truth;
- clean-environment replay reproduces the released artifact from immutable inputs;
- golden cohorts cover the required industries and failure modes;
- release gates block invalid artifacts and preserve an auditable decision trail.

## 24. Pragmatic delivery profile

This profile is the first usable service release. It does not reduce the target state. It selects the smallest coverage set that supports a complete, independently tested service release, then adds model families without changing the source-of-truth rule or service boundary.

### 24.1 Initial coverage boundary

The first production profile (`us-gaap-public-v1`) covers only:

- U.S.-domiciled SEC registrants reporting under U.S. GAAP, with a usable filing history and one common-equity class that the service can resolve;
- mature non-financial companies through FCFF DCF;
- high-growth companies through a guarded transition-to-margin DCF when the required operating facts exist;
- market price and consensus observations as degraded comparison signals only.

The first profile returns `unsupported` or `abstain` for IFRS filers, banks, insurers, REITs, regulated utilities, commodity-dependent cyclical issuers, pre-revenue biotech, conglomerates/SOTP, unresolved multiple share classes, and any issuer whose reporting basis or identity cannot be proven. It does not expose legacy REIT FFO multiples or any other legacy model as a proxy. These families can be added later under separate model and accounting profiles while retaining the V1 service envelope.

The initial model registry contains exactly two eligible model IDs: `fcff_dcf` for mature non-financial issuers and `transition_fcff_dcf` for high-growth non-financial issuers. Both use one calculation engine and capital-bridge policy. `transition_fcff_dcf` is not a permission to invent a path to mature margins: its forecast must be supported by filed operating evidence and explicit, reviewer-approved assumptions. If retention or cohort data is not disclosed, the model may qualify only when it does not use that driver and another filed operating path supports the transition. If the transition cannot be defended, the result is `abstain`.

### 24.2 Priority order

Implement the following slices in order. Do not start calibration or user-interface work for a value that fails an earlier slice.

1. **Canonical input and provenance.** Define one typed valuation input, one source snapshot manifest, and one provenance record. Require `as_of`, `available_at`, `filed_at`, accession, source URL, content hash, unit, currency, and policy version.
2. **Data-quality states.** Add `verified`, `provisional`, `degraded`, `unsupported`, `abstain`, and `error` to the API and report. Replace silent zero-filling and silent provider fallback with explicit codes.
3. **Accounting correctness.** Make SEC and Arelle output the primary accounting path. Enforce units, periods, dimensions, duplicate-fact selection, filing version, and fatal EFM or DQC blocks for the initial cohort.
4. **Calculation correctness.** Fix the FCFF SBC policy, WACC composition, share scope, debt and cash bridge, preferred stock, leases, and non-controlling interest. Add invariant tests before adding new models.
5. **Model eligibility.** Add required fields, forbidden conditions, minimum quality, and abstention to `ModelSpec`. Remove the unconditional `dcf_standard` fallback when no candidate is eligible.
6. **Replay and release gate.** Generate a manifest from immutable inputs. Re-run the deterministic engine without network access. Block release when replay, provenance, or quality contracts fail.
7. **Calibration evaluation.** Build the point-in-time label and report path for one or two forecast metrics, such as revenue growth and operating margin. Keep calibration inactive until the target-specific OOS evidence passes its predeclared promotion policy. Keep consensus-relative adjustment in a separate diagnostic path.
8. **Cohort monitoring.** Start with a fixed engineering cohort of at least 20 cases across at least five industry groups. It must include positive cases for both eligible models and explicit abstention cases for out-of-profile issuers, missing or conflicting facts, and ambiguous share identity. Track missingness, abstention, provider fallback, signed bias, median absolute error, and replay pass rate.

The 20-case cohort is a pragmatic engineering and replay minimum, not a statistical claim that calibration is reliable. It contains at least 10 positive, independently checked valuations (at least five per eligible model across five industry groups) and at least 10 explicit abstention/degraded cases. Keep it separate from the chronological calibration/OOS cohort. For every promoted calibration artifact, report the target, model and sector cohort, `N`, label availability, missingness, abstention, raw/calibrated/naive metrics, uncertainty intervals, and the policy version that defines promotion. If the evidence is insufficient for a stable estimate, leave calibration inactive. Do not use a universal sample-size number without documenting why it is suitable for that target and cohort.

### 24.3 First implementation slices

Implement the first service release in these ownership slices. Keep each slice inside `fundamental-service`; do not import the existing agent's internal modules.

| Slice | Service-owned responsibility | Completion evidence |
| --- | --- | --- |
| Public API and domain contracts | Request, response, identity, quality, model, valuation, and error types | Contract fixtures reject missing versions, invalid statuses, and untraceable values. |
| Source snapshots and point-in-time facts | SEC acquisition, filing versions, taxonomy metadata, canonical facts, and immutable raw evidence | Amended-filing fixture selects only facts available at the requested timestamp and replays offline. |
| Accounting quality | Arelle 2.47.4 integration, the SEC EFM profile loaded by that runtime with its exact release ID recorded, DQC plugin/rules v31.0.3 with Xule 30055, concept mapping, and reconciliation | The pinned combination passes a startup/version compatibility fixture. Golden filings produce the declared blocking and warning codes; only DQC rules effective for the filing date can block. |
| Model registry and deterministic engine | `ModelSpecV1`, eligibility, calculation graphs, capital bridges, and abstention | Positive, negative, boundary, and independent node-level fixtures pass for each supported model. |
| Provenance, cache, and replay | Immutable manifests, content-addressed cache, artifact references, and offline replay | Cache lifecycle tests pass and a clean replay matches the release hash. |
| Forecast calibration and uncertainty | Point-in-time labels, chronological evaluation, intervals, baselines, and promotion policy | Reports show raw, calibrated, and naive metrics. Calibration remains inactive when evidence is insufficient. |
| Service operations | Authentication, deadlines, readiness, logs, metrics, retention, and recovery | Container tests cover startup, health, timeout, restart, and artifact preservation. |

Keep implementation commands and incident steps in service runbooks. Keep domain contracts and pass or fail rules in this specification.

### 24.4 Practical calibration design

Use a narrow, auditable calibration loop before fitting a broad valuation adjustment:

1. Build a point-in-time dataset from SEC snapshots. Each row contains the valuation timestamp, available facts, forecast metric, and the first later filing that discloses the realized metric.
2. Split rows by time. Keep the final period as an untouched out-of-sample set.
3. Fit a bounded mapping for one metric at a time. Store raw, guarded, and calibrated values together.
4. Compare the mapping with the raw forecast and a naive baseline such as the last reported rate or a trailing median.
5. Promote only when the out-of-sample error improves, the sample count is sufficient, and no sector cohort breaches the quality limit.
6. Expire the artifact when its source, schema, or point-in-time policy changes.

### 24.4.1 Point-in-time label and amendment rules

The realized label is the first subsequently published eligible filing fact after the valuation timestamp, subject to the same fact-level availability and amendment-scope rules as the input dataset. A later restatement may be retained as a separate diagnostic label, but it must not overwrite the label used for the original OOS evaluation. The dataset records the selected accession, publication time, amendment scope, and reason for rejecting any later candidate.

### 24.4.2 Minimum V1 contract freeze

Before implementing each service slice, freeze the machine-readable V1 contract for the artifacts that slice produces. At minimum, the first release must define schemas for `SourceSnapshotV1`, `CanonicalFactV1`, `ValuationInputV1`, `EligibilityReportV1`, `CalculationArtifactV1`, `ReleaseManifestV1`, and the stable error catalog. Each schema must define required fields, unknown-field policy, version compatibility, provenance references, deterministic serialization, and whether it is persistent data or a per-request response. There is no service-owned status transition for a valuation request. Enterprise-only artifacts such as a full `ProvenanceGraphV1` or broad `CalibrationArtifactV1` may be implemented in later slices, but their first released contract must not contradict these V1 semantics.

### 24.4.3 Binding initial implementation decisions

The following decisions are binding for `us-gaap-public-v1`; implementation does not reopen them without a versioned change to this specification.

| Decision | Initial policy |
| --- | --- |
| Reporting basis | U.S. GAAP only. IFRS and other reporting bases return `unsupported`; they require a later accounting profile and dedicated fixtures. |
| Issuer and security scope | U.S.-domiciled SEC registrant; consolidated issuer facts; one resolved common-equity class for per-share output. Ambiguous issuer, ADR, partnership, preferred-only, or unresolved multi-class allocation returns `abstain` or `unsupported`. |
| Eligible models | `fcff_dcf` and `transition_fcff_dcf` only. Banks and all other sector-specific models are deferred and abstain in this profile. |
| Runtime and XBRL validation baseline | Arelle `arelle-release==2.47.4`; the SEC EFM profile loaded by that runtime, with its exact release ID and hash recorded in the validation profile; XBRL US DQC plugin/rules `v31.0.3` with Xule `30055`. Lock package hashes before implementation and pass a startup/version compatibility fixture before enabling accounting operations. Only rules effective for the filing date may block; approved but not-yet-effective DQC rules are recorded as advisory. A later Xule release requires a compatibility fixture before adoption. |
| Taxonomy package coverage | Bootstrap the immutable package registry with the 2026 SEC-supported standard taxonomies and every taxonomy release referenced by the initial golden filings and their five-year histories. Requests referencing an unregistered/unresolvable taxonomy return `unsupported` or `abstain`; add a package only through reviewed registry release and replay fixtures. |
| Historical operating baseline | Candidate rule only: use the latest five fiscal years available as of the request and require at least three complete, comparable annual periods. The rule grants at most `provisional` until model-specific representative coverage and chronological out-of-sample evidence validates it. An underpowered cohort leaves the supported threshold unset. Quarterly facts may support freshness checks but do not silently replace missing annual history. |
| Forecast horizon | Five explicit annual forecast periods followed by a steady-state terminal period. Every year-level driver is an explicit traceable assumption; no LLM-generated numeric value or silent default is permitted. |
| Terminal value | Gordon growth on normalized year-six FCFF. Require positive normalized FCFF, `WACC > terminal_growth`, terminal growth no greater than the trailing ten-year nominal U.S. GDP CAGR available in the same ALFRED vintage (a conservative ceiling, not a forecast), and explicit convergence of margin, reinvestment, and return on invested capital. At the base case, terminal value may contribute at most 85% of enterprise value for `verified`; a contribution above 85% and at most 90% is `provisional` with a warning; above 90% returns `abstain`. Failure returns `abstain`; no alternate terminal formula is selected implicitly. |
| Cost of capital | Calculate WACC from explicit, traceable components: 10-year U.S. Treasury par yield at or before valuation time; a dated public U.S. equity-risk-premium and industry-beta reference release; issuer debt cost and tax treatment; and market-value capital weights. A versioned deterministic Fundamental policy automatically approves only complete, source-profile-matched, point-in-time evidence. It abstains on ambiguous SIC mapping, unlicensed use, missing observations, or unsupported methods; no per-candidate human or AI approval is required. No default WACC or current-vintage value may leak into historical replay. |
| Tax policy | Forecast cash taxes explicitly. A temporary or negative effective tax rate is not extrapolated as steady state; a versioned deterministic policy resolves the normalized tax assumption from dated issuer and jurisdiction evidence and shows it separately from reported tax facts. Missing geographic or period scope abstains; a fixed country rate is not silently assigned to a multinational issuer. |
| Share-based compensation | Keep SBC as an operating expense in FCFF and set the V1 SBC add-back to zero. Include dated award dilution under the treasury-stock method and separately identified non-SBC share changes. Do not add forecast dilution for the same SBC expense. If award data or share scope is unknown, abstain. |
| Capital bridge | Report cash, gross debt, lease liabilities, preferred claims, non-controlling interests, and other declared adjustments separately. Every component is `present`, `confirmed_absent`, `unknown`, or `unsupported`; any `unknown` component capable of changing equity value blocks `verified` status. |
| Reconciliation tolerance | After unit and currency normalization, a reported accounting residual must be no greater than the greater of one unit of the least precise contributing fact, USD 1, or 1e-9 times the largest absolute side. A larger residual needs a named presentation, FX, rounding, or mapping exception and cannot be `verified` without reviewer approval. |
| Arithmetic | Released FCFF V1 uses `decimal-50-end-of-year-v1`: `Decimal` precision 50 and `ROUND_HALF_EVEN` in a fixed service-local context (Emin -999999, Emax 999999, clamp 0; InvalidOperation, DivisionByZero and Overflow traps), restored after each call. Preserve that precision through the calculation and round only for display. This reconciles the prior 34-digit target with the V1 model inventory; adopting 34 digits requires a new numerical/model policy and replay evidence, without rewriting existing artifacts. Same-runtime golden replay must match the canonical serialized result exactly. Independent challenger tolerance is at most the greater of USD 1 absolute or 1e-9 relative for equity value, and USD 0.000001 per share. |
| Calibration | Forecast calibration is not required to activate the first release. For V1 revenue-growth and operating-margin targets, the primary metric is MAE in percentage points and the interval is an 80% central interval. Calibration remains inactive until its predeclared, time-separated OOS cohort contains at least 30 eligible labels for the target and model, at least 10 labels in each promoted industry cohort, improves the raw and naive baselines by at least 10% on the primary metric with a two-sided 95% bootstrap interval for the improvement above zero, and has an observed interval coverage whose two-sided 95% Wilson interval has a lower bound of at least 70%. The report still shows raw and naive metrics and uncertainty. The 20-case engineering corpus is never calibration evidence. |
| Human approval | Approval belongs to the caller's workflow. The caller may send an optional `CallerApprovalEnvelopeV1` containing the exact `input_digest`, approver identity, decision, and authorization evidence. The service may validate and echo that envelope, but it does not persist, transition, or manage approval state. A digest mismatch is rejected; the calculator itself remains stateless and never waits for or creates approval. |
| Free-data rule | No paid API, subscription, or data license is required. If a free source's terms do not permit the intended use, it is excluded; the service degrades or abstains instead of scraping around the restriction. |

`ValuationInputV1` has seven top-level required groups: `identity` (CIK, issuer name, domicile, reporting basis, security/share-class identity, currency); `valuation_context` (valuation timestamp, immutable `data_snapshot_id`, source-selection policy, coverage profile); `historical_facts` (canonical fact references for the required field set below); `assumptions` (five-year forecast drivers, WACC components, terminal growth, tax normalization, dilution and scenario); `uncertainty` (explicit scenario and Monte Carlo specification when requested); `quality` (fact statuses, issue codes, and eligibility state); and `provenance` (snapshot, mapping, parser, taxonomy, and policy versions). It contains no service approval state or approver identity. The service computes `input_digest` over the complete canonical `fundamental-json-v1` request, including the immutable snapshot, model, assumptions, uncertainty, and resolved policy versions. A caller may bind its own approval envelope to that digest, but the service does not store an `ApprovalRecordV1`. Missing groups are schema errors. Missing required economic inputs are eligibility failures, never zeroes.

The initial required canonical field set is: revenue; cost of revenue; operating income; income before tax; income tax expense; net income; depreciation and amortization; capital expenditure; operating current assets and liabilities needed for working-capital change; cash and equivalents; current and long-term interest-bearing debt; operating and finance lease costs and liabilities by current/long-term scope; SBC expense; basic and diluted weighted-average shares; and point-in-time common shares outstanding. Preferred claims, non-controlling interests, convertibles, and other share classes must be represented as present/confirmed-absent/unknown even when the model ultimately rejects the issuer. Every fact includes period, unit, currency, scale, dimensions, source accession and context, availability timestamp, original QName, canonical mapping decision, and quality status.

For lease consistency, operating lease expense remains in operating cash flow and operating lease liabilities are disclosed but not deducted again as debt. Finance lease obligations are included in debt, the equity bridge, and WACC weights. If the filing cannot distinguish the two classes or provide the required expense/obligation facts, lease treatment is `unknown` and a verified result is blocked.

The WACC proposal follows one calculation path: `Re = Rf + levered_beta * ERP`; `levered_beta = unlevered_industry_beta * (1 + (1 - normalized_tax_rate) * D/E)`; and `WACC = E/(D+E)*Re + D/(D+E)*Rd*(1-normalized_tax_rate)`. `Rf` is the 10-year U.S. Treasury par yield. `ERP` and the unlevered industry beta come from the latest dated Damodaran public U.S. dataset released no later than the valuation timestamp. `D` is reported interest-bearing debt plus finance-lease obligations at carrying value; `E` is point-in-time common shares multiplied by an approved, lawful, free-source closing price. `Rd` is a reviewer-approved marginal cost-of-debt assumption with cited evidence; trailing interest expense divided by average debt may be shown as a diagnostic but is not silently treated as a marginal borrowing rate. The normalized marginal tax rate is the same reviewed rate used by the forecast. Operating lease costs remain in FCFF and operating-lease liabilities are excluded from `D`; finance-lease obligations are included in `D` and the equity bridge. If any component is unavailable or its source is not permitted for the intended use, require a reviewer-supplied component with provenance or abstain. WACC, beta, ERP, tax, and capital weights are assumptions, not verified accounting facts, and the report must show their sensitivity.

### 24.4.4 FCFF input source and historical sufficiency matrix

This matrix is the source and quality contract for the only released FCFF models. The Fundamental service owns fact selection, formulas, forecast policy, eligibility, and abstention. The caller may resolve issuer identity, send the selected valuation timestamp, apply its configured approval policy, and collect a supported assumption override; it must not derive a second set of valuation formulas or policy values.

For every row, `available_at` must be no later than the valuation timestamp. SEC duration facts are aligned by fiscal year and period start/end; instant facts are aligned to the fiscal period end. The snapshot retains the original QName, context and dimensions, unit/currency/scale, filing accession, filed/accepted time, amendment relationship, source content hash, selected fact ID, rejected candidates, and selection reason. Filing time or an observed market publication time controls availability; capture time never moves evidence backward. Each versioned quality policy defines a numeric maximum age or a period-based freshness rule for every source. A field without a pinned freshness rule cannot be `verified`; its result remains `provisional` or `abstain`. A missing, stale, conflicting, unlicensed, or unmapped value is `unknown`/`unsupported`, never zero or a placeholder. A result is `degraded` only where the model policy declares the limitation non-blocking; otherwise it is `provisional` pending review or `abstain` with a typed reason.

Historical facts and historical derived metrics are read-only. Correct a source fact by adding an immutable snapshot or a reviewed mapping release. A user may override only an assumption that the selected model policy marks editable. The override preserves its automatic value and evidence, records `ManualProvenance(description, author, modified_at, review_status, evidence_links, automatic_value_ref, automatic_provenance_ref)`, changes the input digest, and recalculates. The description records the reason. The caller owns approval and binds confirmation to that digest. Missing company guidance, analyst consensus, Search, or LLM output does not block either default model.

| Input and model applicability | Classification, source owner, formula/policy version, and evidence | Period, as-of, freshness, and quality gate | Fallback, editability, and review or abstention |
| --- | --- | --- | --- |
| Issuer, security, share class, reporting basis, currency, and valuation timestamp (`fcff_dcf`, `transition_fcff_dcf`) | SEC submissions, filing identity, and service identity resolution; observed identity under `identity-v1` and snapshot selection under `pit-v1`. Preserve CIK, accession, security/class mapping, and source snapshot ID. | Identity is resolved as of the request; selected facts and observations must satisfy `available_at <= valuation_timestamp`. Reject facts with incompatible issuer, class, currency, or reporting basis. | A genuine ticker/class ambiguity may request caller clarification. No valuation model is selected until identity resolves; unresolved multi-class allocation abstains. Identity is not a valuation assumption override. |
| Revenue and prior-year revenue (`fcff_dcf`, `transition_fcff_dcf`) | SEC Company Facts or filing XBRL; `SEC-observed`; canonical mapping plus `annual-history-metrics-v1`. Annual growth is `revenue_t / revenue_(t-1) - 1`, with both exact fact IDs retained. | Annual duration facts for aligned fiscal years in the latest five available at the request timestamp; use only periods published by that timestamp. Require comparable scope, currency, duration, and mapping. | Never substitute quarterlies, peer data, guidance, or a placeholder for a missing year. A zero/negative or near-zero prior revenue denominator makes growth undefined. The existing three-of-five rule is only a candidate pending chronological cohort evidence below; the model cannot be marked `verified` from that rule alone. |
| Cost of revenue and gross profit (`transition_fcff_dcf` required; `fcff_dcf` diagnostic when available) | SEC duration facts; `SEC-observed`; `annual-history-metrics-v1`. `gross_profit = revenue - cost_of_revenue`; `gross_margin = gross_profit / revenue`. | Same fiscal-year and availability rules as revenue. Require mapped, comparable cost classification and nonzero, stable revenue. | An unsupported cost mapping makes gross margin unavailable. Transition assumptions that rely on gross margin then become provisional or abstain; no peer/vendor substitute. This historical fact is not manually editable. |
| Operating income / EBIT (`fcff_dcf`, `transition_fcff_dcf`) | SEC duration fact, with reviewed issuer-extension mapping where needed; `SEC-observed`; `annual-history-metrics-v1`. `EBIT_margin = operating_income / revenue`. | Same annual periods as revenue; filing, concept, unit, and continuing-operations scope must align. | Conflicting or low-confidence extension mappings block verified eligibility. A zero/negative or near-zero revenue denominator makes the ratio undefined. No hidden operating-margin floor or analyst estimate is substituted. |
| Income before tax, tax expense, and net income (`fcff_dcf`, `transition_fcff_dcf`) | SEC duration facts; `SEC-observed`; reported effective tax is `income_tax_expense / income_before_tax`. Normalized marginal tax is a separately reviewed assumption under `tax-policy-v1`, never the reported ratio relabeled as normalized. | Annual facts are aligned to the same fiscal period and filing availability time. Quality checks identify tax benefits, loss periods, discrete items, jurisdiction changes, and conflicting concepts. | Negative/zero/near-zero pretax income or a temporary/negative effective rate cannot be extrapolated. Resolve normalized tax from a dated reviewed source with sensitivity; if unavailable, request the minimum reviewer-supplied tax input or abstain. Preserve reported facts unchanged. |
| Depreciation and amortization (`fcff_dcf`, `transition_fcff_dcf`) | SEC duration facts and reviewed mappings; `SEC-observed`; `annual-history-metrics-v1`, with source fact IDs for each component and aggregate. | Annual duration matching revenue/EBIT periods; validate units, signs, acquired-intangible treatment, and duplicate/overlapping facts. | Missing or conflicting D&A blocks the reinvestment derivation; do not set it to zero. A reviewer may resolve a mapping or provide a permitted, cited assumption, but cannot relabel it as a filing fact. |
| Capital expenditure (`fcff_dcf`, `transition_fcff_dcf`) | SEC cash-flow duration facts for property/equipment and any explicitly included capitalized software; `SEC-observed`; `annual-history-metrics-v1`. Normalize cash outflow sign once and retain each component fact ID. | Annual duration and availability must match the operating period. Check investing/cash-flow classification, unit, signs, and extension mappings. | Unmapped or absent material CapEx blocks reinvestment and the verified baseline. Do not use an industrial-extension-only value or current-period placeholder. Any allowed inclusion/exclusion is a versioned mapping/formula policy, not an edit to the fact. |
| Operating working-capital components (`fcff_dcf`, `transition_fcff_dcf`) | SEC instant facts for current operating assets and liabilities; `SEC-observed`; `operating-working-capital-v1`. Include explicitly mapped receivables, inventory, contract assets, payables, accrued operating liabilities, and deferred revenue as specified by policy. `OWC = operating_current_assets - operating_current_liabilities`; `change_OWC_t = OWC_t - OWC_(t-1)`. | Instant facts at each comparable fiscal period end, selected as available at the valuation timestamp. Require the same consolidation scope and a complete component set. | Exclude cash, interest-bearing debt, lease financing, and other financing balances; do not use total current assets minus total current liabilities as a proxy. Missing/conflicting components block reinvestment; no manual fact edit or silent zero. |
| NOPAT and reinvestment (`fcff_dcf`, `transition_fcff_dcf`) | `Computed`; `historical-metrics-v1`; `NOPAT_t = EBIT_t - normalized_cash_taxes_t`; `reinvestment_t = CapEx_t - D&A_t + change_OWC_t`. `reinvestment_rate = reinvestment_t / NOPAT_t` is defined only when NOPAT is positive and outside the versioned near-zero denominator limit. Retain periods, formula, units, signs, and all input fact IDs. | Derived only from facts and reviewed normalized-tax inputs aligned to the same fiscal periods and pinned policy version. | Do not infer a ratio from loss-making or near-zero NOPAT. The dollar components remain visible, but a forecast requiring an undefined ratio is provisional/abstained until a supported policy resolves it. No current-assets-minus-current-liabilities proxy. |
| Stock-based compensation, award instruments, and dilution (`fcff_dcf`, `transition_fcff_dcf`) | SEC filing facts and dated award/share evidence; `SEC-observed` plus `sbc-dilution-v1`. SBC remains an operating expense and add-back is zero; existing awards use the treasury-stock method at an approved valuation-date quote. | Expense is annual duration; awards and common shares are point-in-time and available by valuation timestamp. Preserve instrument class, exercise price, quantity, and quote identity/time. | No double counting or automatic future dilution for the same SBC expense. Missing award detail, quote, or share scope blocks verified per-share value; request reviewer evidence or abstain. A supported assumption edit retains the automatic value/evidence and ManualProvenance. |
| Cash, non-operating cash, current/long-term interest-bearing debt, and other senior claims (`fcff_dcf`, `transition_fcff_dcf`) | SEC instant facts; `SEC-observed`; `capital-bridge-v1`. Preserve cash, restricted cash, short- and long-term borrowings, preferred claims, non-controlling interest, and other claims separately. | Latest eligible balance-sheet facts at or before the valuation timestamp, as of their reported period end. Check currency, scope, amendments, classification, reconciliation, and the versioned freshness limit. | Every component is `present`, `confirmed_absent`, `unknown`, or `unsupported`. Unknown value-changing claims block verified valuation. Do not convert missing claims to zero or treat cash as operating working capital. Caller may clarify a genuinely ambiguous classification; otherwise abstain. |
| Operating and finance leases (`fcff_dcf`, `transition_fcff_dcf`) | SEC instant liabilities and annual expense facts; `SEC-observed`; `lease-treatment-v1`. Operating lease expense stays in FCFF and liability is not deducted again; finance lease debt is included in WACC debt and the equity bridge. | Preserve current/non-current classification and annual expense period; all filing observations obey point-in-time selection. | If the filing does not distinguish lease classes or required amounts, treatment is unknown and verified value is blocked. No silent all-leases-as-debt or all-leases-as-operating fallback. Reviewer resolution must cite filing evidence. |
| Basic and diluted weighted-average shares; point-in-time common shares and dilutive instruments (`fcff_dcf`, `transition_fcff_dcf`) | SEC duration facts for EPS/share metrics and SEC DEI/filing facts for point-in-time shares; `SEC-observed`; `share-scope-v1`. Keep weighted-average shares distinct from as-of diluted shares used for equity value. | Weighted-average facts align to the annual income period; outstanding shares and instruments are instant facts with publication no later than valuation time. | Reject mixed periods/classes or nonpositive counts. Missing split adjustment, award detail, or class allocation blocks per-share value. No substitution of weighted-average shares for point-in-time shares without an explicit policy. |
| Five-year revenue, margin, tax, and reinvestment forecast vectors (`fcff_dcf`, `transition_fcff_dcf`) | `Model-derived`, owned by Fundamental service; `fcff-history-forecast-v1` or `transition-history-forecast-v1` must pin anchor, normalization/fade, bounds, convergence, and input periods. The forecast formulas are the model formulas in sections 13.2 and 24.4.3; every forecast period links to historical computed metrics and policy version. | Five annual forecast periods begin from the latest eligible filed period and are followed by the normalized sixth-year terminal period. As-of is the valuation timestamp; no future filing is an input. | No forecast is an observed fact. If history, model policy, or transition path is insufficient, return the policy's provisional/abstain reason; do not use hidden defaults or ask the user to re-enter routine values when the policy is valid. A supported override records ManualProvenance and changes the digest. |
| Transition-model filed operating evidence (`transition_fcff_dcf` only) | Pinned SEC filing evidence selected by accession; `SEC-observed` when the fact is structured and mapped, otherwise a cited filing passage is evidence for reviewer interpretation under `transition-evidence-v1`. Search/LLM is outside the default path. | Evidence must be in the pinned snapshot, published by the valuation timestamp, identify metric/unit/fiscal period, and pass filing and extraction quality checks. | Missing or ambiguous path-to-normalized-margin evidence triggers the minimum necessary reviewer clarification, provisional result, or abstention as the transition policy declares. No analyst consensus, peer fact, or uncited narrative is substituted. |
| Risk-free rate (`fcff_dcf`, `transition_fcff_dcf`) | Market-observed U.S. Treasury 10-year par yield; Fundamental public-source registry and `wacc-policy-v1`; preserve URI, terms reference, publication/availability time, captured bytes, and hash. | Observation date must be no later than valuation timestamp and satisfy the WACC freshness limit. For replay, use a retained historical observation, never today's yield. | A live capture is not historical availability evidence. The executable policy must verify the published observation and freshness; otherwise it abstains. Never use a static rate as an observation. |
| Equity risk premium, industry beta, and industry mapping (`fcff_dcf`, `transition_fcff_dcf`) | Reference assumptions from a dated Damodaran U.S. release under `wacc-policy-v1`; service source registry records the source and terms URL. Beta is mapped through the versioned SIC-to-reference-industry mapping; it is an assumption, not an issuer fact. | Select only a release available by the valuation timestamp. Preserve release date, mapping version, industry resolution, URI, and content hash. | The provider is registered for public-source capture but is not in the active FCFF model source register or automatic assumption resolution. Its terms URL is not legal-use approval. Until both source rights and wiring are verified, require reviewed manual components or abstain; ambiguous industry requires reviewer selection. |
| Cost of debt, normalized marginal tax, debt/equity weights, and market capitalization (`fcff_dcf`, `transition_fcff_dcf`) | `Policy-resolved` only from reviewed assumption packages with source/method/version; `market-observed` equity value requires point-in-time common shares and an approved lawful free closing quote. `D` includes interest-bearing debt and finance leases; `E = shares * quote`; `WACC = E/(D+E)*Re + D/(D+E)*Rd*(1-tax)`. | Inputs are tied to the valuation timestamp and each provider's publication time/freshness. Preserve price vendor, quote date, terms, currency, and hashes. | A closing-price source is not registered in the current Fundamental source catalog. Trailing interest expense/average debt is diagnostic only. Without a permitted quote or defensible marginal cost of debt, require a cited reviewer assumption package or abstain; do not silently assign beta 1.0, default WACC, or current market inputs to a historical replay. |
| Terminal growth and normalized year-six state (`fcff_dcf`, `transition_fcff_dcf`) | `Policy-resolved`/`Computed`, never SEC-observed; `terminal-policy-v1`. Growth is bounded by WACC and the trailing ten-year nominal U.S. GDP CAGR from the same eligible ALFRED vintage. Year-six FCFF records margin, reinvestment, and return-on-invested-capital convergence. | Macro vintage and model policy must be available by valuation timestamp; annual terminal state follows forecast year five. | Missing macro vintage or explicit terminal policy, nonpositive normalized FCFF, or `growth >= WACC` abstains. Enforce the section 24.4.3 terminal-value share limits. A reviewer may provide a sourced assumption only within the same bounds; no company fact or static growth default. |
| Company guidance, analyst forecasts, and debt-term research (`fcff_dcf`, `transition_fcff_dcf`) | Optional forward evidence, separate from the baseline and deferred to #355. Search may discover sources only after opt-in; an LLM extraction is a claim that must retain the source passage and quality/licensing metadata. | Each reference keeps issuer, metric, unit, fiscal period, publication/retrieval time, source identity, content hash, and license status. | Their absence never triggers abstention when SEC history and approved policies pass. They cannot overwrite a baseline or enter the calculation without an explicit user selection, preserved automatic evidence, ManualProvenance, a new digest, and recalculation. |

The #359 cohort report counts only the listed revenue concept `RevenueFromContractWithCustomerExcludingAssessedTax`. Its 0/100 revenue coverage does not establish that the SEC lacks historical revenue. A point-in-time Company Facts audit for CIK `0001539778` found qualifying `us-gaap:Revenues` facts for decision accession `0001477932-16-007985`, while the listed concept had no qualifying facts in the measured periods. The response SHA-256 is `6bfb258021d1976a47e06b42f3bebacbcef28d5b30fb54085a102cd839acd1c1`.

Treat `us-gaap:Revenues` as a candidate mapping, not a universal alias. #352 must retain the original QName and mapping decision version, and qualify mappings by taxonomy package, issuer context, duration, unit, currency, and reporting scope. Duplicate, overlapping, or conflicting candidates remain unresolved and block verified eligibility. Re-run the predeclared cohort after reviewed mappings without replacing issuers. Keep unmatched facts visible as source evidence, but return an explicit unsupported, provisional, or abstained outcome when the canonical mapping is not approved.

The active request producer currently asks for only `revenue`, `operating_income`, `cash`, `debt`, and `diluted_shares` as point-in-time fields, adding `filed_operating_evidence` for the transition model. #352 must replace that narrow set with a multi-period service-owned history read. At minimum, the service response/request must represent aligned annual duration series for revenue, cost of revenue, operating income, pretax income, tax expense, net income, D&A, CapEx components, operating working-capital components, SBC, and weighted-average shares; instant series for cash, debt, lease classes, preferred claims, non-controlling interests, common shares, and dilutive instruments; and the transition filing-evidence reference. Each series entry carries fact ID, original/canonical concepts and mapping version, value/unit/currency/scale, period type/start/end or instant, dimensions/scope, accession/form, filed/accepted/available/captured timestamps, amendment/supersession metadata, quality/issues, and pinned snapshot/content hashes. The service returns selected and rejected candidates with reasons so the caller never re-selects facts.

The accepted #356 report at `docs/acceptance/issue-356-history-sufficiency-v1.json` has SHA-256 `ce5f3f374071c63181dfa6fbd0b5a0501ebb6abd1ba3062ff7e73f0ba92fbc76`. Its primary fixture cohort has three issuer clusters, no next-original-filing pairs, and no primary fact labels. The one-issuer Apple diagnostic has eight decision windows per model, seven first-subsequent filings, and no complete measured label sets. Its period-level Wilson 95% interval `[0.0, 0.35433]` is descriptive only, and the report supports no history threshold. The report's sample-size policy requires 100 independent issuer clusters for its target Wilson margin of 0.10; periods from one issuer do not add independent observations.

The accepted #359 report at `docs/acceptance/issue-359-sec-cohort-v1/report.json.gz` has uncompressed SHA-256 `1a3995af98d3fda2166873c25f0ba981d89016ae6f6f98dc4515a077eac41b9f`; its fixed manifest SHA-256 is `afad3f92f2597383d16afec2cc85850fbf5919106d3cb827a6e8112022836242`. The report retains all 100 issuer clusters, records 0/100 eligible issuers and 0/100 complete first-subsequent labels for each model under the listed mappings, and reports no historical Fundamental Service forecast accuracy. Its status is `underpowered` and `supported_history_threshold` is null. The revenue coverage result is mapping-limited as described above. This report does not validate the three-of-five candidate.

The three-of-five annual-history rule in section 24.4.3 remains an unvalidated candidate gate. It cannot grant `verified` eligibility. The merged #359 cohort is underpowered, so `supported_history_threshold` remains null. Keep affected results `provisional` when the candidate rule and all other evidence gates pass; abstain when required facts are missing, conflicting, or mapped with unresolved scope. Calibration remains separate and inactive until the target/model label and sample gates in section 24.4.3 pass.

### History-threshold validation sequence

Keep the delivery order #351, #352, #353, #354, and #355. #351 accepts the source and quality matrix, the provisional-only candidate rule, and explicit abstention conditions. It does not claim that any numerical history threshold has been validated. Do not change the candidate from three of five to five years without evidence.

The merged #352 supplies the canonical Fundamental Service forecast composer. Use that same service logic for the historical replay now tracked by #376; #361 owns the persistent source-preparation and valuation flow. For each model, evaluate predeclared candidate history lengths in chronological walk-forward order. At each decision date, select only SEC facts available by that date and label forecasts with the first subsequent original filing that meets the declared criteria. Report forecast error, cohort coverage, independent issuer counts, and uncertainty. Retain failed or incomplete cases in the predeclared denominator. If the evidence remains underpowered, keep the threshold null and results provisional or abstained. This follow-up does not change the fixed delivery order.

Before a revenue concept can support a verified result, review its issuer, fiscal period, unit, currency, dimensions, and reporting scope against the filing and version the mapping decision. `us-gaap:Revenues` and other exact-tag candidates remain unapproved until that review passes. The #361 candidate-tag screen is not canonical mapping evidence. An unreviewed or conflicting mapping cannot feed verified eligibility.

Current wiring and intended-use status at the #351 review baseline:

| Source | Intended fields and class | Registry and observed wiring | Terms, freshness, and default-path status |
| --- | --- | --- | --- |
| SEC Company Facts and pinned SEC filings | Filing-observed issuer facts, periods, accessions, amendments, and filed transition evidence. | SEC source adapters, snapshots, facts, and acquisition are implemented in Fundamental Service. The Agent Core producer currently resolves only the point-in-time subset stated above. | SEC source identity and timestamps are retained. Respect SEC fair-access/User-Agent/rate limits; historical facts use filing availability and immutable snapshot rules. This is the only core accounting path presently backed by issuer facts. |
| U.S. Treasury yield curve | Market-observed 10-year risk-free rate. | Present in `PUBLIC_SOURCE_SPECS`, capture fixtures, and the current model source register; generic source capture is implemented. Automatic resolution into the WACC assumption in a normal valuation request is not evidenced. | Treasury terms reference is recorded, but intended-use review and freshness policy must be recorded with a release. A capture fixture is not proof of normal-path consumption. |
| FRED/ALFRED | Point-in-time macro series, especially GDP vintage used for terminal-growth ceiling. | Registered with generic public-source capture and fixtures; not listed in the active FCFF model source register or proven to flow into valuation assumptions. | FRED terms URL is recorded. ALFRED vintage must be no later than valuation time. Captured observations are not automatically valuation inputs. |
| Damodaran public U.S. data | Dated ERP and unlevered industry beta reference. | Registered with generic public-source capture; absent from the active FCFF model source register and automatic WACC resolution. | A data URL is recorded, but no intended-use/license determination is in the release evidence. Exclude from verified valuation until rights, vintage, mapping, and path are reviewed. |
| Free point-in-time common-share closing quote | Market capitalization/equity weight and treasury-stock dilution. | No provider is registered in the Fundamental source catalog and no end-to-end price-to-WACC path is evidenced. | Provider, permissible reuse, quote calendar/as-of rule, corporate-action adjustment, and freshness limit remain unresolved. Do not claim automatic WACC readiness. |
| Marginal cost of debt and normalized tax assumption | Reviewer-supplied/policy-resolved assumptions, not filing facts. | No approved debt-cost provider or automatic reviewer-approved assumption package is evidenced; reported interest/debt is diagnostic only. | Requires a cited, dated, sensitivity-tested reviewer input or abstention. No static or trailing ratio is silently promoted to current cost. |
| Company guidance, analyst estimates, Search/LLM | Optional forward reference only. | Not part of the default valuation source register or required request path; separately governed by #355. | No call occurs in a normal request. Missing credentials or evidence cannot degrade an otherwise qualified baseline. |

Source registration and a terms URL do not establish legal permission for retention or the intended commercial use. The source owner must record the actual terms decision, rate limits, retention conditions, and intended use in the versioned release evidence before a source can support `verified` inputs.

### Automatic market-policy admission

This target policy supersedes human-review requirements in older WACC implementation notes. Fundamental Service must use a pinned deterministic evaluator to approve source and assumption evidence automatically. The evaluator is not yet wired for the complete market-input set, so no complete market policy is admitted today. A future decision must bind source bytes, parser and policy versions, timestamps, issuer scope, and input digest. Missing or conflicting evidence abstains; approval of an assumption never changes its quality status to `verified`. AI checking may be added as a separate future control, but it is not required for this policy.

| Input | Free-source policy | Automatic decision |
| --- | --- | --- |
| Risk-free rate | U.S. Treasury's dated 10-year par-yield curve, captured with the published observation date, source URI, bytes, and hash. | Approve only when observation availability and freshness are proven at the valuation timestamp. A later capture of a historical table alone cannot backdate availability. |
| ERP and beta | Damodaran's dated U.S. aggregate ERP and industry beta downloads/archive. The issuer SIC comes from its SEC filing and resolves through a pinned industry mapping. | Approve only a pre-valuation release and reproducible selected cells. Keep only the published aggregate values needed for calculation and attribution; do not copy underlying commercial company-level records. Ambiguous SIC mapping abstains. |
| Borrowing cost | SEC facility terms plus the exact contracted benchmark and tenor. TLF discloses CME Term SOFR + 210 basis points. The New York Fed official API is available for overnight SOFR, but overnight SOFR is not Term SOFR. | Require an exact benchmark match, dated observation, and preserved contract accession. The New York Fed capture path retains an exact single-date response with retrieval-time availability; it cannot establish historical publication time. Do not substitute overnight SOFR, Treasury yield, or trailing interest expense. If the term benchmark is not admitted, the complete policy abstains. |
| Capital weights | SEC interest-bearing debt and finance-lease facts; SEC point-in-time common shares; and a lawful, dated free-source closing quote. | Derive weights deterministically from eligible inputs. Missing quote rights, security identity, share scope, or availability abstains; weights must sum to one. |
| Normalized tax | SEC tax reconciliation and jurisdiction evidence under a versioned tax policy. Damodaran's U.S. country-tax reference is not automatically the issuer's worldwide marginal tax rate. | Approve only when the policy can resolve the issuer's applicable tax scope. Never silently use a fixed 25% rate for a multinational. |
| Terminal growth ceiling | A BEA archived GDP release or ALFRED vintage available by valuation time; derive the declared ten-year nominal GDP CAGR ceiling from that same vintage. | Require an explicit versioned terminal-growth rule, the historical GDP vintage, and `growth < WACC`. Missing vintage or rule abstains; no static two-percent default. |

Even when every source check passes, the resulting valuation assumptions remain policy-approved assumptions with sensitivity evidence. Forecast and valuation calculations continue to use the formal #352 Fundamental Service composer.

### Provider-neutral macro evidence

`macro_series.MacroSeriesProviderPort` is the injected source boundary for macro
vintages. `reproduce_macro_vintage` supplies an explicit canonical series ID to
the port and checks series/provider identity and each original artifact's hash,
version, URI, terms and capture time. The requested series is part of the
provider call, so one adapter can support multiple series without caller-side
provider switches. `MacroSeriesVintageV1` carries chronologically ordered
observations with periods and units and source artifacts in canonical order;
canonical serialization identifies the immutable vintage. Source adapters never
choose a valuation formula, approve a market policy or write storage.

`BeaNominalGdpVintageProvider` and `NewYorkFedSofrVintageProvider` implement the
same port. BEA's bounded profile reads NIPA table 1.1.5 annual nominal USD GDP
from a Q4 third-estimate archive and binds its published date to the official GDP
release page. The archive directory can be dated after the news release. The
profile therefore waits until the archive day has ended before allowing the full
history, while rejecting date conflicts, incomplete/corrupt tables and unknown
formats. The SOFR provider reproduces the existing single-date overnight profile
and retains capture-time availability; it does not supply CME Term SOFR.

Provider-neutral `select_macro_vintage` applies the valuation cutoff and rejects
conflicting latest releases. `NominalGdpGrowthCeilingV1.derive` computes a nominal
GDP CAGR from eleven consecutive annual observations over ten years in the
existing fixed Decimal context. Its digest binds the selected vintage, policy
version, cutoff and result. This produces a ceiling, not a terminal-growth
assumption or market approval. The implementation does not yet wire a complete
market-policy evaluator into preparation; the numerical flow remains blocked.

Future providers implement the same port and canonical series identity, periods,
units and availability evidence. They can reuse selection and the GDP ceiling
policy without provider-specific branches in either policy or the #352 composer.
Alternative-provider tests prove that GDP policy accepts the same canonical
series from a second provider, rejects a provider that changes series/source
identity, and is unaffected by source input order. SOFR and BEA also exercise
the shared contract. HTTP capture, immutable content storage, source-use
admission and release signing remain separate owning boundaries.

This provider contract currently covers macro series only. Treasury rates,
Damodaran reference tables, issuer quote vendors, and facility benchmark
observations need equivalent provider adapters before they can be swapped at
runtime. Do not imply those providers are configured by the macro abstraction.

The first schemas use strict unknown-field rejection and no implicit defaults. Their minimum field groups are:

| Artifact | Required V1 content |
| --- | --- |
| `SourceSnapshotV1` | schema and snapshot IDs; issuer/security identity; valuation timestamp; captured-at time; source records with URI, role, availability/capture time, HTTP status, content hash, media type and terms reference; accession/form/filed-at records and amendment links; taxonomy manifest reference; parser and policy versions. |
| `CanonicalFactV1` | fact ID; issuer/security; original concept QName; canonical field and mapping decision ID; typed value or explicit missing state; unit/scale/currency; structured context and dimensions; economic period; available/filed/captured times; accession; taxonomy package hash; source content hash; quality status and issue references. |
| `ValuationInputV1` | the required groups defined above; immutable snapshot and fact references; explicit assumption and uncertainty provenance; requested model/profile; canonical serialized form and `input_digest`. |
| `CallerApprovalEnvelopeV1` | optional caller-owned approval evidence: `input_digest`; approver identity or external authorization reference; approved-at time; decision; rejection reason when applicable; caller workflow version. The service validates the binding but does not persist or transition this record. |
| `PolicyResolutionV1` | pinned policy ID/version; every resolved field; caller value, policy value, precedence decision, and provenance; resulting assumptions and resulting `input_digest`. |
| `EligibilityReportV1` | input digest; every candidate model/version; required and missing fields; forbidden conditions; quality issues; eligibility status; selected model or abstention code; policy version. |
| `CalculationArtifactV1` | input digest; optional caller-approval envelope reference; model/schema/calculation/policy versions; named DAG nodes with formula ID, input references, Decimal result, unit and provenance; enterprise/equity bridge; per-share result; scenarios/sensitivity; output hash and quality state. |
| `ReleaseManifestV1` | artifact and input hashes; source snapshot IDs; taxonomy/DTS package hash; Arelle, EFM/DQC plugin and rule signatures; mapping, model, calculation, assumption, quality and calibration versions; runtime/build identity; replay result. |

Stable boundary error codes for V1 are `IDENTITY_AMBIGUOUS`, `SNAPSHOT_NOT_FOUND`, `POLICY_NOT_FOUND`, `SOURCE_UNAVAILABLE`, `SOURCE_RATE_LIMITED`, `FILING_NOT_AVAILABLE_AS_OF`, `TAXONOMY_PACKAGE_INVALID`, `XBRL_VALIDATION_BLOCKED`, `FACT_MAPPING_UNRESOLVED`, `FACT_CONFLICT`, `MODEL_UNSUPPORTED`, `MODEL_INELIGIBLE`, `INPUT_DIGEST_MISMATCH`, `CALLER_APPROVAL_DIGEST_MISMATCH`, `UNCERTAINTY_INVALID`, `CALCULATION_BUDGET_EXCEEDED`, `REPLAY_MISMATCH`, `DEPENDENCY_INCOMPATIBLE`, and `INTERNAL_FAILURE`. Each error also carries a retryable flag, correlation ID, and safe diagnostic reference. Message text is not a programmatic contract.

The initial taxonomy path uses Arelle with pinned `validate/EFM` and `validate/DQC` plugins and the filing's complete DTS. It does not introduce a custom Arelle plugin. For every filing, create `TaxonomyPackageManifestV1` with the entrypoint, all schema/linkbase/import resources, namespace URIs, taxonomy/package identifiers, source locations, byte hashes, Arelle version, plugin versions, validation profile and package hash. Resolve the DTS into a content-addressed local package; offline replay must not fetch taxonomy resources from the network. Never substitute the newest taxonomy release for the taxonomy referenced by a historical filing. The service maintains an allowlisted taxonomy-package registry from SEC/XBRL-published releases and filing-referenced issuer extensions; a new package or rule release is an additive version, never an in-place update to prior artifacts.

Issuer extensions remain first-class source concepts. The service-owned `CanonicalMappingV1` registry maps a source QName to a canonical field and records the taxonomy package hash, evidence (XBRL anchor and applicable presentation/calculation/definition relationships, label/reference, context, unit and period compatibility), sign/scale transformation, confidence class, reviewer, approval time and mapping-policy version. Labels or embedding similarity alone cannot establish a verified mapping. New or changed mappings enter `unresolved` until reviewed and golden fixtures pass; valuation-critical unresolved or ambiguous mappings block eligibility. Mapping decisions live in the Fundamental service, not in custom Arelle plugins.

The first release uses Arelle's existing EFM/DQC plugins for filing validation. Custom Arelle plugins are deferred. Add one only when a reproducible validation rule requires Arelle lifecycle hooks or model/DTS access that cannot be expressed in the service-owned post-parse quality rules; the plugin must emit normalized findings and may not own canonical accounting mappings, model selection, or valuation policy. Pin plugin code and rule resources by release identifier and content hash. A rule or plugin update creates a new validation profile and requires the affected release cohort to be rerun.

There is no service-owned valuation operation state machine. `validate` checks a complete request against the selected snapshot, model, policy, assumptions, uncertainty specification, and quality gates without calculating a value. `calculate` executes the deterministic graph synchronously within a declared compute budget. `calculate-with-policy` first resolves a pinned policy into concrete assumptions, returns those resolved assumptions and provenance, and then invokes the exact same calculator. All three paths return a result, an explicit `abstain`/`unsupported`/`degraded` quality status, or a stable error in the same response; none creates a valuation session, approval row, queue item, or server-owned job. A caller may compare the returned `input_digest` with its own approval envelope before presenting or persisting the result. Replay uses the immutable manifest and input snapshot offline, and is a pure calculation request rather than a lookup of operation state.

Do not use current price, analyst target price, or consensus as the realized label for intrinsic value. Those observations may remain in a separate market-signal evaluation.

### 24.5 Practical release thresholds

The first profile must enforce these hard requirements:

- 100% of released valuation fields have provenance or a computation expression;
- 100% of historical replay rows pass the `available_at` check;
- 0 silent model fallbacks and 0 silent provider fallbacks;
- 100% deterministic replay hash match for the release cohort;
- 0 blocking XBRL, EFM, DQC, unit, period, or share-scope issues in `verified` artifacts;
- at least 20 golden cases: at least 10 positive independently checked valuations (at least five per eligible model across five industry groups) and at least 10 explicit abstention/degraded cases;
- calibration reports show raw and naive metrics where labels exist, calibrated metrics only for an eligible promoted artifact, and an explicit inactive/rejected reason otherwise;
- every unsupported or abstained case contains a machine-readable reason and missing-evidence list.

The release profile must be declared before running the cohort. It pins numeric tolerances, blocking issue codes, missingness and fallback limits, calibration promotion rules, and interval metrics. Any change creates a new quality-policy version and requires the affected cohort and replay evidence to be rerun.

These thresholds are the minimum release profile. A deployment may tighten them, but it may not loosen them without a versioned policy change and new evidence.

### 24.6 Deliberately deferred work

The following work belongs to the target state but should not block the first dependable profile after the initial coverage boundary is complete:

- full insurer, REIT NAV, regulated utility, cyclical, biotech, and conglomerate model families;
- broad Monte Carlo distributions with learned cross-parameter correlations;
- automated model-selection learning across all sectors;
- full component-level error decomposition across extraction, accounting, forecast, discount rate, terminal value, and capital bridge;
- market-outcome portfolio optimization;
- free-web consensus scraping as a primary input;
- LLM-generated numeric assumptions without a source or approved policy;
- compatibility shims for disposable legacy payloads.

Deferred work remains visible as `unsupported`, not as a hidden approximation.

### 24.7 Practical completion condition

The practical profile is complete when a fixed cohort can run from public snapshots to a deterministic, traceable report without network access, and every unsupported or degraded path is explicit. At that point the system is usable for the declared coverage boundary and ready to expand one model family at a time.

## 25. Enterprise service design and validation criteria

This section records the enterprise-level questions that govern the service design. It defines what specialists add, which methods and tools they use, and what evidence an independent reviewer can inspect.

### 25.1 Requirement breakdown

The service program has four outcomes that must remain separate:

| Outcome | Question it answers | Evidence required |
| --- | --- | --- |
| Data correctness | Did the system use the right issuer fact, at the right time, with the right accounting meaning? | point-in-time snapshot, XBRL context, unit, filing accession, Arelle and reconciliation results |
| Model correctness | Was the chosen model economically applicable and complete for the company? | versioned `ModelSpec`, eligibility report, forbidden-condition checks, abstention evidence |
| Calculation correctness | Did deterministic formulas produce the declared result from validated inputs? | typed input, formula graph, invariant tests, independent reference calculation, replay hash |
| Decision usefulness | Does the result and its uncertainty support a decision without overstating confidence? | scenario and interval report, OOS calibration, market-signal evaluation kept separate |

The project must not use a good result in one column to compensate for a failed result in another. Accurate arithmetic on a future-restated fact is still a data failure. A well-sourced fact passed to an inapplicable model is still a model failure.

### 25.2 What top specialists add without being asked

An experienced valuation, accounting, data, and model-risk team would add these requirements before implementing features:

- **A formal domain vocabulary.** Define issuer, security, share class, economic period, filing version, observation time, accounting fact, assumption, model, scenario, estimate, forecast, and realized label. Reject overloaded fields such as `as_of` when the code needs both economic time and publication time.
- **A bitemporal data policy.** Store both the period described by a fact and the time the fact became available. Keep original filings and later restatements as different versions.
- **An accounting ontology and mapping review.** Map standard and extension concepts, units, dimensions, signs, continuing operations, segment scope, and calculation relationships. Record mapping confidence and a human-review path for ambiguous extensions.
- **A model inventory and risk register.** For each model, record purpose, owner, assumptions, known limitations, supported cohort, input dependencies, validation evidence, change history, and retirement conditions.
- **A failure policy before a success path.** Decide which missing, stale, contradictory, or degraded values block a valuation, lower its status, or cause abstention. Do not let individual callers invent fallback behavior.
- **An independent reference implementation.** Calculate a small set of cases with a separate implementation or spreadsheet fixture. Compare node-level values, not only the final per-share result.
- **A leakage and revision audit.** Prove that backtests, calibration, and model selection never read a future filing, a later restatement, a revised macro series, or a target price that was unavailable at the decision timestamp.
- **A survivorship and identity audit.** Include delisted issuers, ticker changes, share-class changes, mergers, and bankruptcies where public history permits. Do not build a historical cohort from today's active ticker list.
- **An error decomposition.** Report extraction, accounting normalization, forecast, discount-rate, terminal-value, and capital-structure contributions separately. A calibration fit must target the component whose error it can measure.
- **A scenario-dependence policy.** Record dependencies between growth, margins, reinvestment, risk, and dilution. Do not sample correlated assumptions independently without evidence.
- **A market-expectations diagnostic.** Use reverse DCF to describe the operating assumptions implied by a dated price when useful. Do not use the reverse-DCF result as intrinsic-value ground truth.
- **A capital-structure policy.** Define basic versus diluted shares, options, restricted units, convertibles, preferred stock, leases, non-controlling interests, repurchases, and SBC treatment before tuning a DCF.
- **A numerical policy.** Define decimal versus binary floating-point boundaries, currency conversion, scale, rounding, tolerance, overflow, underflow, discounting convention, and non-finite-value handling.
- **A change and retirement policy.** Version facts, mappings, policies, formulas, schemas, and calibration artifacts independently. Retire a model only after its callers are switched, its fixtures and reports point to the replacement, and its replay manifests remain reproducible.
- **Operational controls.** Define source-rate limits, cache retention, raw-data access, credential boundaries, incident handling, SLOs, and provider-degradation behavior. A reproducible valuation needs reproducible operations.
- **Decision-focused reporting.** Show value drivers, model limitations, data quality, uncertainty, abstention reasons, and what evidence would change the result. A single confidence number is not an audit trail.

These are part of the target because they protect the system from the most expensive failure: a plausible number that cannot be explained, reproduced, or corrected.

### 25.3 Professional methods, theories, and hard tools

Use the following methods as the default technical approach. Each method must produce an artifact or test that can be reviewed.

| Area | Method or theory | Tooling and repository application |
| --- | --- | --- |
| Architecture | Domain-driven design, hexagonal boundaries, vertical-slice ownership, contract-first service design | service-owned capabilities, internal-service contracts, `architecture_guard.py`, architecture action report |
| Data time | Bitemporal or point-in-time modeling, append-only snapshots, event-style versioning | `SourceSnapshotV1`, `available_at`, accession selection, immutable content hashes |
| Accounting | XBRL context and dimensional semantics, calculation-linkbase checks, US GAAP or IFRS concept mapping | SEC EDGAR, Company Facts, Arelle, EFM, DQC, taxonomy package hashes |
| Data quality | Explicit quality dimensions, severity policy, reconciliation and contradiction checks | typed `QualityStatus`, normalized issue schema, block or warn release gates |
| Valuation | FCFF, WACC, residual income, regulatory-capital models, NAV, SOTP, normalized-cycle analysis | pure calculation graphs, `ModelSpec`, unit-aware inputs, independent formula fixtures |
| Numerical correctness | Dimensional analysis, interval bounds, conservation invariants, monotonicity and sensitivity checks | `Decimal` monetary values, declared precision, property tests, finite-value guards, node-level tolerances |
| Model risk | Risk-based model inventory, independent validation, limitations, monitoring, change control, and challenge | model-risk register, validation report, challenger implementation, approval and expiry fields; use SR 26-2 only as a scoped reference |
| Forecast evaluation | Rolling-origin chronological splits, cohort analysis, proper scoring rules, confidence intervals, and purge or embargo when outcome windows overlap | point-in-time labels, raw and naive baselines, reliability reports, and promotion gates |
| Uncertainty | Scenario analysis, sensitivity, empirical error distributions, calibrated prediction intervals | deterministic seeds, interval coverage, interval score, dominant-driver report |
| Software verification | Contract tests, property-based tests, mutation tests for critical formulas, differential tests, offline replay | Pydantic contracts, Hypothesis or equivalent property tests, reference engine, replay manifests |
| Operations | Immutable artifacts, content-addressed ingestion, repeatable calculation, bounded retries, source-health monitoring | artifact repository, source snapshot manifest, cache keys, structured diagnostics and SLO metrics |

Do not introduce a tool only because it is common in another organization. The tool must close a named evidence gap, have a clear owner, and produce a repeatable check in this repository.

### 25.4 Objective standards and external verification

No single external source can prove an intrinsic value is correct. Independent checks establish whether the service used valid evidence, applied the declared method, and reported measured forecast performance without presenting any of those checks as proof of intrinsic value.

Use these external references and verification channels:

- **SEC and XBRL.** Reconcile canonical facts with the issuer's filing, XBRL contexts, units, dimensions, accession, and filing date. Use Arelle's validation output and the applicable EFM or DQC rules. SEC Company Facts is an index and aggregation of non-custom taxonomy facts for an entity; it cannot replace the complete filing or the issuer's extension taxonomy, so valuation-critical custom facts must be checked against the original Inline XBRL package.
- **Taxonomy lifecycle.** Use the SEC's [EDGAR XBRL guide and technical specifications](https://www.sec.gov/submit-filings/technical-specifications) to identify filing rules; use the [XBRL US DQC rule catalog and effective dates](https://xbrl.us/home/priorities/data-quality/rules-guidance/) to decide which rules are active for a filing. Use Arelle's [taxonomy package](https://arelle.readthedocs.io/en/latest/) and [plugin development](https://arelle.readthedocs.io/en/latest/plugins/plugins.html) documentation for runtime behavior. Pin the actual release artifacts and hashes used by each service build.
- **Official macro sources.** Use FRED or ALFRED vintages, Treasury yields, BEA, BLS, Federal Reserve, and FDIC data for their declared domains. Store the vintage or publication time.
- **Accounting standards.** Use the public SEC reporting guidance, FASB or IFRS taxonomy references, and issuer filing presentation for concept meaning. Do not use a market-data page to resolve accounting semantics.
- **Model-risk governance.** [SR 26-2](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm) replaced SR 11-7 on April 17, 2026. It applies as supervisory guidance to its banking scope and is a reference, not a certification or direct requirement for this service. Use the [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework) when an ML component affects a decision or confidence label.
- **Forecast calibration.** Use rolling-origin out-of-sample evaluation and strictly proper scoring rules. Use targets that the service can observe later, such as filed revenue or margin. Do not calibrate intrinsic value to a share price, analyst target, or consensus estimate.
- **Independent calculation.** Recompute selected cases in a separate module or spreadsheet with independently entered formulas. The challenger must not import the production calculator's internal functions.
- **Metamorphic and property tests.** Verify that increasing cash cannot reduce equity value when all else is constant, increasing debt cannot increase equity value, terminal growth remains below WACC, a zero growth shock does not change unrelated nodes, and share dilution does not increase per-share value under the declared policy.
- **Historical replay.** Re-run from immutable snapshots in an offline environment. The result must match the recorded artifact or identify the first changed node and version.
- **Out-of-sample monitoring.** Compare raw, calibrated, and naive forecasts on a time-separated cohort. Report confidence intervals, sample counts, missingness, abstention, drift, and provider fallback rates.
- **Reproducible build evidence.** Pin runtime, parser, taxonomy, policy, model, and calibration versions. A clean environment must produce the same output hash for the same manifest.

The acceptance claim is therefore bounded: the system can prove that it followed the declared data, model, formula, and uncertainty contracts. It cannot prove that an intrinsic value equals a future market price.

### 25.5 Target-compatible service contract chain

The isolated service must create the contracts that the enterprise stage will consume from its first release. It must not expose a temporary payload and plan to replace it later.

```text
SourceSnapshotV1
    -> CanonicalFactV1
    -> ValuationInputV1
    -> ModelSpecV1 and EligibilityReportV1
    -> CalculationArtifactV1
    -> UncertaintyArtifactV1
    -> CalibrationDatasetV1 and CalibrationArtifactV1
    -> ProvenanceGraphV1 and ReleaseManifestV1
```

The service may use internal adapters between its source, domain, and persistence layers, but the request/response fields, input and result digests, timestamps, status codes, and provenance references must be stable from the first release. No per-request operation ID is part of the calculation contract.

### 25.6 Existing agent to service boundary

| Existing agent boundary | New service boundary | Integration rule |
| --- | --- | --- |
| SEC and market source access | `SourceSnapshotV1` owned by the service | the service fetches and caches source data; the agent does not pass raw filing dictionaries |
| `FinancialReportModel` and `FinancialStatementsPayload` | `FinancialHealthArtifactV1` response reference | the agent maps the typed response summary into its own DTO; it never becomes the service's data store |
| `TraceableField` and `TraceableFieldModel` | service-owned provenance envelope | the service returns provenance references and report projections, not shared internal trace objects |
| `ParamBuilderPayload` and `ParamBuildResult` | `ValuationInputV1` and `PolicyResolutionV1` | the service reads its own canonical facts and policy versions; explicit caller assumptions remain visible and authoritative |
| `ModelSpec`, `ModelCandidate`, `ModelSelectionResult` | service-owned `ModelSpecV1`, `EligibilityReportV1`, `SelectionArtifactV1` | the agent receives the selected model and eligibility evidence through the calculation response |
| `CalculationGraph` and model graph functions | service-owned calculation engine and `CalculationArtifactV1` | no runtime import from the old agent; independent formula fixtures are mandatory |
| `valuation_flow.py` and `JSONObject` report assembly | service client plus response mapper | the agent keeps only request orchestration, approval, and product projection |
| existing replay reports and cohort gates | service-owned `ReleaseManifestV1` and `ReplayReportV1` | the service owns replay and release evidence; the agent stores references and user-visible summaries |
| current forward-signal calibration | service-owned `CalibrationDatasetV1` | consensus-relative monitoring remains a separate operation and label contract |

### 25.7 No-rebuild service guardrails

Each service-build slice must satisfy all of these conditions before it is considered complete:

1. The data and calculation contracts are defined in the service boundary and use the shared `internal.v1` context contract.
2. The service owns its source snapshots, cache, canonical facts, model registry, policies, and release artifacts; it does not own caller workflow state.
3. The existing Fundamental agent can call the service through a typed client and map the response without importing service internals.
4. Fixed fixtures, independent expected outputs, and the service replay manifest agree within declared tolerances.
5. The service exposes stable error codes, deadlines, readiness, correlation IDs, input/result digests, and explicit degraded or abstain outcomes. Repeated calculation requests are safe because the calculator is pure; no request idempotency table is required.
6. No service domain code imports the old agent's `JSONObject`, concrete provider, workflow, or private domain modules.
7. The service passes architecture, contract, behavior, offline replay, independent formula, and cache lifecycle tests.
8. A failed service request cannot cause the agent to calculate a second hidden valuation locally.

The new service may replace formulas because it is a greenfield implementation. It must preserve only the externally declared service contract and evidence semantics, not the internal structure of the old agent.

### 25.8 Enterprise service phases and exit gates

1. **Contract freeze and service ownership.** Register the data, policy-resolution, validation, and calculation schemas, model-risk inventory, ownership map, retention policy, and error catalog. Exit when every service contract has a version and owner.
2. **Source snapshot and point-in-time facts.** Build immutable raw snapshots, filing selection, taxonomy metadata, and canonical facts. Exit when amended filings and later restatements replay correctly.
3. **Quality and accounting validation.** Normalize Arelle, EFM, DQC, unit, period, dimension, and reconciliation issues. Exit when block and warn behavior is deterministic on golden fixtures.
4. **Typed valuation input and calculation engine.** Build `ValuationInputV1`, formula invariants, and independent reference cases. Exit when the engine has no I/O or LLM dependency and every output has a trace.
5. **Eligibility and abstention.** Build model specifications and selection artifacts. Exit when an ineligible model cannot reach calculation and an unsupported archetype produces a useful abstention.
6. **Artifact, cache, and replay contract.** Build provenance graph, release manifest, content-addressed cache behavior, and offline replay. Exit when a clean environment reproduces cohort artifacts.
7. **Calibration and uncertainty.** Build point-in-time labels, OOS splits, purge or embargo, naive baselines, interval metrics, and promotion or expiry policy. Exit when rejected calibration remains inactive and the report explains why.
8. **Service boundary verification.** Add the backend client, fake service, contract tests, deadline and retry tests, and one cutover fixture set. Exit when the client can consume the service without importing its implementation.
9. **Model-family expansion.** Add banks, insurance, REIT NAV, regulated utilities, cyclical, biotech, and SOTP one family at a time. Each family reuses the same service contracts.

No phase may introduce a temporary field that is absent from the target contract, a hidden fallback that cannot be replayed, a shared database table with the agent, or a second source of truth. This is the condition that prevents the isolated service from becoming a wrapper that must later be rebuilt.

### 25.9 Assumptions and open decisions

The binding decisions for the initial service release are recorded in section 24.4.3. There are no unresolved architecture or product-scope decisions that block implementation. Each model release still must publish its own numeric tolerances, quality profile, calibration threshold, and lawful source register before its cohort evaluation; these are versioned release artifacts, not discretionary implementation defaults.

Ownership is fixed as follows: contracts and canonical facts remain under the Fundamental service until another service has a demonstrated need for a shared contract; mapping approval belongs to the Fundamental data domain and uses a versioned deterministic policy, a separately identified trusted machine key, and source-bound observation scopes; supported automatic decisions must be reproduced by the read-only release canary; unsupported, missing and conflicting evidence abstains; retained independent human reviews remain valid historical evidence but are not a mandatory mapping gate; the independent challenger must be maintained separately from production calculation code and reviewed by someone other than the model implementer; raw snapshots remain immutable while any valuation or calibration artifact references them, and unreferenced failed/preparation snapshots may be removed after 90 days. Source-specific terms take precedence over this retention rule.

### 25.10 Non-operating assets in the FCFF bridge

The current `fcff_dcf-v2` and `transition_fcff_dcf-v2` models use
`calculator-v2` and `fcff-forecast-composer-v5`. Requirements profiles v3 add
the required instant role `non_operating_assets`; the full FCFF profile has
32 scalar roles and transition FCFF additionally requires filed operating
evidence. No history threshold is promoted by this change.

`non_operating_assets` means the complete classified amount outside both cash
and operating working capital. It is a required, finite, nonnegative currency
amount; it has no zero default. Formal preparation selects a verified,
release-bound fact at the cash balance date and from the same original. The
assumption retains its fact ID, source hash, policy and date. Unknown scope,
missing facts, future evidence and conflicting values abstain.

Preparation rejects reuse of a positive cash or working-capital observation,
including observations retained inside a computed accounting role. An explicit
negative cash component in an approved total-minus-cash classification is an
exclusion rather than a second positive asset. Structural overlap checks do not
establish semantic completeness: the mapping policy must establish all included
and excluded asset classes, investment receivables, and any cash-included funds
from original evidence. The current direct automatic mapping policy has no rule
that approves a complete non-operating asset role; it retains abstention.

The existing calculator adds this amount once after operating enterprise value.
The independent challenger and conservation check include the same declared
bridge term. New model and policy identities prevent prior approvals from
authorizing the changed inputs. Retained records are not rewritten; old model
versions cannot be executed as the current graph. Synthetic bridge amounts and
zero assumptions in engineering fixtures do not approve an actual issuer's
classification or absence. #381 and #361 require real-source completion and
independent review before closure.

## 26. Isolated service architecture decision

### 26.1 Decision

Build the new enterprise Fundamental implementation as an independently deployable service with two logical planes in one initial deployable: a persistent public-data/policy plane and a stateless calculation plane. Keep the existing Fundamental agent unchanged while the service is built and verified. The agent calls the service through a typed internal-service client and maps the response into product-facing domain data.

This decision is worth the extra boundary for this project. Fundamental valuation is a critical component, the current agent contains mixed orchestration and valuation responsibilities, and the new design needs independent source caching, point-in-time storage, replay, calibration, and release control. An isolated service gives those concerns one owner and lets the service be tested against immutable data without booting the whole agent graph. The boundary is not a second workflow engine: the caller owns conversation state, human approval, retries, and presentation, while the service owns evidence and deterministic computation.

This is not a claim that a service boundary removes work. It changes the work from an in-place refactor to a greenfield implementation plus a contract cutover. The project still needs service tests, contract tests, deployment checks, failure handling, and independent validation. A request that cannot be completed within the synchronous compute budget returns a stable budget or deadline error; it does not become a hidden server-side job.

### 26.2 Ownership boundary

| Existing product backend | Fundamental service |
| --- | --- |
| user authentication and authorization context | service authentication and data/calculation authorization |
| conversation, workflow state, approval pause, and user-facing projection | stateless data and calculation contracts; no valuation workflow state |
| agent-facing client and response mapping | request/response schemas and stable error catalog |
| product artifact references and display summaries | raw source snapshots, canonical facts, policy registry, and content-addressed data cache |
| product UI and user decisions | canonical facts, XBRL validation, model registry, calculations, calibration, provenance, replay, and release artifacts |

The service owns its database tables, cache keys, schema versions, and artifact lifecycle. The agent must not read the service database, pass raw filing dictionaries, or implement a local valuation fallback after a service failure. A service failure is an explicit unavailable or degraded outcome.

### 26.3 Service contract

Use the existing internal-service pattern from [`src/shared/internal_services`](../../finance-agent-core/src/shared/internal_services/README.md): `internal.v1` signed context plus service-owned `fundamental.v1` data and calculation schemas. A correlation ID and request digest are observability and integrity fields; they are not identifiers for a server-side valuation session.

The first API set is intentionally small and separates persistent data reads from stateless computation:

- `GET /v1/data/facts`: read canonical facts and their quality/provenance references from a caller-selected immutable snapshot.
- `GET /v1/data/snapshots/{snapshot_id}`: inspect the snapshot manifest, source hashes, availability cut-off, taxonomy and parser versions, and coverage status.
- `GET /v1/policies/{policy_id}`: inspect the exact versioned assumption and quality policy that a convenience calculation may resolve.
- `POST /v1/valuation/validate`: validate a complete `ValuationInputV1` and return eligibility, missing evidence, normalized assumptions, and `input_digest`; it never calculates a value.
- `POST /v1/valuation/calculate`: calculate from a complete explicit `ValuationInputV1` using the immutable `data_snapshot_id` and caller-supplied assumptions and uncertainty specification.
- `POST /v1/valuation/calculate-with-policy`: resolve a caller-pinned `policy_id` against the immutable data snapshot, apply only fields not explicitly supplied by the caller, return the resolved assumptions and provenance, and invoke the same deterministic calculator used by `/calculate`.
- `GET /livez` and `GET /readyz`: report process liveness and dependency readiness without exposing source, cache, database, or credential details.

External provider access belongs only to the data-ingestion path that creates a new immutable snapshot. Validation and calculation read the selected snapshot and policy registry; they never fetch a current filing, price, macro series, or taxonomy resource as a hidden side effect.

The explicit calculation body is shaped like this (the concrete field schemas are versioned and reject unknown fields):

```json
{
  "contract_version": "fundamental.v1",
  "data_snapshot_id": "snapshot-abc",
  "model_id": "fcff_dcf",
  "valuation_timestamp": "2026-11-03T00:00:00Z",
  "assumptions": {
    "forecast": {},
    "wacc": {},
    "terminal_growth": "0.02"
  },
  "uncertainty": {
    "mode": "monte_carlo",
    "samples": 10000,
    "seed": 12345,
    "parameters": [
      {
        "path": "assumptions.forecast.revenue_growth[0]",
        "distribution": "triangular",
        "lower": "0.05",
        "mode": "0.08",
        "upper": "0.12"
      }
    ],
    "correlations": [],
    "invalid_draw_policy": "reject"
  },
  "caller_approval": null
}
```

`calculate-with-policy` uses the same body but replaces or supplements `assumptions` with a pinned `policy_id` and explicit caller overrides. The resolver applies policy values only to omitted fields, records the precedence decision for every field, and passes the resulting `ValuationInputV1` to the same calculator. It is a convenience input builder, not a second valuation implementation.

The calculation request must not accept a precomputed intrinsic value or an unverified raw financial report. It must contain an immutable `data_snapshot_id`, `model_id`, `valuation_timestamp`, complete explicit assumptions, and an uncertainty specification whenever scenarios or Monte Carlo are requested. The policy endpoint may provide system parameters, but `/calculate-with-policy` must return the exact resolved values and provenance and must never silently override explicit caller fields. Verified calculations require a pinned `policy_id`; an unpinned active/latest policy is exploratory only and must be marked accordingly. The request digest binds every input that can change the result:

```text
input_digest
contract_version and service_version
issuer and security identity
valuation_timestamp and source_snapshot_id
model_id and model_version
policy_id and resolved policy version, when used
calculation_status: completed, abstained, rejected, unavailable, or error
quality_status: verified, provisional, degraded, unsupported, abstain, or error
selected model and eligibility report
resolved assumptions and caller-provided assumptions with provenance
intrinsic-value projection and uncertainty projection when calculation completes
quality issue codes and missing-evidence list
provenance graph reference and release manifest reference
Monte Carlo seed, sampler version, requested/valid/invalid sample counts, and convergence diagnostics when applicable
result_hash, correlation_id, evaluated_at, and retryability
```

Large provenance graphs, filing packages, and calibration reports remain behind artifact references. The agent converts the response projection, not the entire service domain graph, into its own DTO.

`calculation_status` describes the outcome of this synchronous request only; it is not persisted state. `quality_status` describes the evidence and result quality, and they are independent. For example, a request can return `calculation_status: completed` with `quality_status: abstain`, or `calculation_status: rejected` with `quality_status: unsupported`. Repeating the same request is safe because the calculator is pure over the pinned snapshot and complete input; the service does not need an idempotency key or a request record. The caller may persist the response or artifact reference in its own workflow.

The HTTP adapter uses `200 OK` for a validated response, including explicit abstention or degraded quality, `400` for malformed contracts, `401` for failed internal authentication, `404` for missing snapshots or policies, `409` for a caller approval or input-digest conflict, `422` for stable domain refusals such as model ineligibility or invalid uncertainty, `408`/`504` for deadline exhaustion, and `503` for unavailable dependencies. Every non-success response includes the error code, `correlation_id`, and retryability. The service never places a numeric value in an error or abstention response; calculation responses are synchronous and have no asynchronous operation status.

### 26.4 Cache and data lifecycle

The service cache is content-addressed and keyed by source URL or filing identity, query parameters, source version, taxonomy package, validation profile, and parser version. A cache hit is valid only when its source and policy versions match the request.

Keep these stores separate:

- raw source snapshots, which are immutable and retained for replay;
- parsed filing and taxonomy cache, which can be rebuilt from raw snapshots;
- canonical fact store, which is versioned and point-in-time addressable;
- valuation and calibration artifacts, which reference input snapshots and policy versions;
- operational cache and locks, which may expire and must never be the only copy of a valuation result.

Calculation artifacts may be persisted as immutable, content-addressed release evidence or returned for caller-owned persistence. They are records of completed pure computations, not mutable operation state, approval state, retry state, or a prerequisite for repeating the calculation.

The service must be able to rebuild derived stores from retained raw snapshots. A cache reset must not destroy the evidence needed to reproduce a released valuation.

Derived artifacts carry a dependency manifest listing the source snapshot IDs, parser and taxonomy versions, mapping package, quality profile, model and calculation versions, assumption policy, and calibration artifact used to create them. When one dependency changes or is invalidated, the service marks only dependent derived artifacts as stale and records the reason; unrelated artifacts remain valid. Rebuild is explicit and append-only. A stale artifact cannot retain `verified` status, and a cache miss or provider error cannot silently promote a rebuilt artifact.

#### Publish data releases without interrupting requests

API replicas serve only published immutable releases. A separately operated scheduler or ingestion runner monitors public sources and builds candidate releases outside the API request path. The runner does not add a valuation session, approval state, or background calculation job. A failed acquisition, parse, mapping review, or validation leaves the current release available.

A candidate release binds the exact source snapshots and canonical facts to compatible taxonomy/DTS packages, parser and validation-rule versions, mapping package, and quality profile. Persist and hash-check every referenced artifact before publishing the release manifest. Activate a profile-scoped release pointer in one database transaction with a compare-and-swap on its expected revision. If another publisher changes the pointer first, reject the stale activation and revalidate the candidate against the new release. Never update a published manifest or mapping in place.

Resolve the active release once at the start of a request and pin its manifest digest, snapshot IDs, mapping package, and compatible policy versions through calculation, response provenance, and replay. An in-flight request continues with its pinned release after activation. New requests may resolve the new release. Requests that supply an explicit immutable snapshot keep that snapshot and its compatible release regardless of the active pointer. A request must never combine facts or mappings from different releases.

Run the candidate through compatibility checks, mapping-scope and review gates, golden fixtures, offline replay, and the applicable Arelle, SEC EFM, and XBRL US DQC rules before activation. Use read-only shadow validation for a canary. Keep valuation-critical new or changed issuer extensions unresolved until an independent data-domain reviewer approves the evidence and the affected fixtures pass. Monitor the activated release against declared freshness, error, latency, and quality limits. Roll back by atomically pointing to the previous compatible release; retain both manifests and all referenced evidence for replay. Record the activation or rollback, actor, release digests, reason, and verification evidence in an append-only audit trail.

Use release-aware cache keys that include the full dependency set. Activation does not require a global cache flush. Use expand-and-contract database migrations so old and new API replicas can read compatible schemas during a rollout. Keep the previous release readable until no request or retained artifact depends on it. Zero-downtime activation does not remove the service availability requirements for PostgreSQL, content storage, or other dependencies.

### 26.5 Why the response mapping cost is acceptable

The response mapping is a controlled cost when the service returns a narrow, versioned projection and immutable artifact references. It is a risk when the agent receives service internals or a second copy of the calculation graph.

Keep the mapping at one boundary:

```text
agent request DTO -> internal.v1 + fundamental.v1 -> service
service response projection + artifact references -> agent domain/UI DTO
```

Do not map each service fact into an old `TraceableField` tree. The agent needs status, key values, explanations, and references. Reviewers can open the service artifacts for the full provenance graph.

### 26.6 Service test strategy

The isolated service must have its own test pyramid:

- domain tests for accounting normalization, model eligibility, formulas, units, and quality severity;
- contract tests for request, response, error, readiness, deadline, digest binding, and version rejection;
- policy-resolution tests proving explicit caller values win, resolved values are returned, and both API paths invoke the same calculator;
- source-adapter tests with recorded SEC and macro fixtures, including amended filings and provider failures;
- golden valuation tests with node-level expected values and independent formulas;
- seeded Monte Carlo tests for reproducibility, convergence, correlation handling, and invalid-draw refusal;
- cache lifecycle tests for hit, miss, stale, invalidation, rebuild, and concurrent population;
- offline replay tests from an immutable manifest;
- calibration tests with point-in-time splits, OOS labels, raw baselines, and rejected-fit behavior;
- service-client tests in `finance-agent-core` using a fake service, without importing service implementation modules;
- container-level tests for startup, readiness, database schema, cache dependencies, timeout, and graceful shutdown.

The existing agent tests continue to cover workflow and response projection. They do not become the service's domain test suite.

### 26.7 Cutover gate

Do not use production traffic until all of these pass on the fixed initial cohort:

1. The service builds from a clean checkout and passes its architecture guard.
2. The service can run without network access from stored source snapshots.
3. Every response has a valid `fundamental.v1` schema, status, issue catalog, `input_digest`, and `result_hash`; a persisted artifact reference is present when the service stores release evidence, otherwise the caller can persist the returned artifact.
4. Independent calculation fixtures match at every declared critical node.
5. Replay reproduces the release artifact hash.
6. The client maps the response without importing service internals.
7. Service failure produces an explicit error or degraded result, and the agent does not calculate locally.
8. Cache reset and service restart preserve released artifact reproducibility.
9. The release record includes source, parser, taxonomy, model, policy, calibration, runtime, and schema versions.

The cutover is one integration change in the existing agent. It does not modify the old valuation implementation. The old implementation can remain untouched as a comparison fixture until the service has passed the cutover and the project makes a separate deletion decision.

### 26.8 Costs and limits

The service boundary adds network latency, deployment configuration, authentication, deadlines, retries, observability, and another failure domain. It also requires service-specific storage and Compose or production health checks.

Those costs are justified only if the team enforces the ownership boundary. If the service calls the old agent for its calculations, shares the agent's database, or returns unversioned dictionaries, the project pays the distributed-systems cost without receiving isolation. That design is not acceptable.

## 27. Primary sources and supporting links

Use primary sources to validate definitions, observations, and tool behavior. The service still owns its acceptance rules and validation evidence.

### 27.1 Data and sector definitions

- [SEC EDGAR API documentation](https://www.sec.gov/edgar/sec-api-documentation) and the [SEC Company Facts example endpoint](https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json)
- [SEC EDGAR technical specifications and taxonomies](https://www.sec.gov/submit-filings/technical-specifications)
- [XBRL specifications](https://specifications.xbrl.org/) and [Arelle documentation](https://arelle.readthedocs.io/)
- [Arelle plugin system and validation plugin development](https://arelle.readthedocs.io/en/latest/plugins/plugins.html)
- [Arelle 2.47.4 release](https://github.com/Arelle/Arelle/releases/tag/2.47.4), [DQC v31.0.3 release](https://github.com/DataQualityCommittee/dqc_us_rules/releases/tag/v31.0.3), and [Xule 30055 release](https://github.com/xbrlus/xule/releases/tag/30055)
- [XBRL US Data Quality Committee rules and effective dates](https://xbrl.us/home/priorities/data-quality/rules-guidance/)
- [FRED API documentation](https://fred.stlouisfed.org/docs/api/fred/) and [ALFRED vintage API](https://fred.stlouisfed.org/docs/api/fred/alfred_api.html)
- [Daily U.S. Treasury par yield curve rates](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics)
- [Damodaran public data and historical downloads](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/data.html)
- [Federal Reserve SR 26-2](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm), [Basel Framework](https://www.bis.org/basel_framework/), and [NAIC Risk-Based Capital](https://content.naic.org/insurance-topics/risk-based-capital)
- [Nareit FFO definition](https://www.reit.com/glossary/funds-operations-ffo) and [Nareit AFFO definition](https://www.reit.com/glossary/adjusted-funds-operations-affo)
- [FERC industry forms](https://www.ferc.gov/industries-data/data-forms) and [18 CFR Part 35](https://www.ecfr.gov/current/title-18/chapter-I/subchapter-B/part-35)
- [FDA clinical research phases](https://www.fda.gov/patients/drug-development-process/step-3-clinical-research) and [ClinicalTrials.gov API](https://clinicaltrials.gov/data-api/api)
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework)

### 27.2 Methods and implementation evidence

- [Strictly proper scoring rules, prediction, and estimation](https://doi.org/10.1198/016214506000001437) defines scoring-rule properties for forecast evaluation.
- [Damodaran valuation data and materials](https://pages.stern.nyu.edu/~adamodar/) provide open valuation references, not issuer-specific truth labels.
- [Current Fundamental flow research](../../docs/research-paper/fundamental-current-flow-tools.md)
- [Agent architecture standard](../../.agents/skills/architecture-standard-enforcer/references/cross-agent-architecture-standard.md)
- [Fundamental source tree](../../finance-agent-core/src/agents/fundamental/)
- [Fundamental backtest runbook](../../finance-agent-core/docs/fundamental_backtest_runbook.md)
- [Fundamental replay input contract](../../finance-agent-core/docs/fundamental_replay_input_contract.md)
- [Fundamental forward-signal calibration runbook](../../finance-agent-core/docs/fundamental_forward_signal_calibration_runbook.md)
- [Fundamental master backlog](../../finance-agent-core/docs/backlog/fundamental-master-backlog.md)

The service target state remains normative if any linked implementation document or source page differs. Record the source release or retrieval date in valuation artifacts when the source can change.
