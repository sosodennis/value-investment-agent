# Market inputs and replaceable sources

Fundamental Service owns source acquisition, source admission, issuer mapping
and market-input policy. The formal #352 composer owns valuation preparation
and calculation. Providers reproduce source evidence; deterministic policies
decide whether that evidence can supply a model input.

## Current inputs

| Model input | Current source and selection | Meaning retained by the service |
| --- | --- | --- |
| Risk-free rate | U.S. Treasury daily ten-year par yield, through `MacroSeriesProviderPort` and `select_market_rate` | Latest eligible daily observation under the currency, age and availability policy. Published percent converts to a fraction. |
| Beta | NYU Damodaran U.S. industry cost-of-capital workbook, through `MarketReferenceProviderPort` | An explicitly adopted industry equity-beta proxy. It is not a measured company beta; unlevered beta cannot silently replace equity beta. |
| Equity risk premium | NYU Damodaran country ERP workbook, through `MarketReferenceProviderPort` | The eligible country row selected using original-bound jurisdiction evidence and a versioned crosswalk. |
| Pretax borrowing cost | The same NYU industry cost-of-capital workbook | An industry borrowing-cost assumption, not the issuer's contracted debt rate. Overnight SOFR cannot silently replace it. |
| Debt/equity capital weights | The same NYU industry cost-of-capital workbook and industry row | Industry capital-policy assumptions, not current issuer market weights. A coherent published pair permits only the existing bounded representation normalization. |
| Terminal growth | Admitted BEA nominal GDP vintage plus the selected long-term risk-free rate | The explicit policy `min(nominal_gdp_cagr, long_term_risk_free_rate)`, with a pinned GDP horizon and freshness bound. It is a stable-growth assumption, not observed company growth. |

SEC original-submission headers supply the issuer's dated SIC and incorporation
jurisdiction. `IssuerClassificationProviderPort`,
`ClassificationCrosswalkProviderPort` and `CountryCrosswalkProviderPort` keep
source classification, reference taxonomy mapping and input selection separate.
A mapped incorporation country is the current policy basis; it does not assert
the issuer's complete geographic revenue or country-risk exposure.

These adapters exist independently of complete real-issuer valuation acceptance.
An approved source or mapping does not establish all accounting roles, a quote,
an approved release, caller approval or a verified history threshold.

## Source suitability

Production market inputs require a maintained structured dataset, a stable API
or download interface, documented field meanings and update rules, and
verifiable version or historical-date evidence. Provider abstractions preserve
these capabilities; they do not make an unsuitable source suitable.

Do not introduce an adapter that extracts a value from an individual article,
blog post, article feed or narrative passage. Finding similar posts in several
years does not establish a dataset contract. The 2025 Damodaran article/feed ERP
candidate investigated under #361/#369 is excluded on this basis. Its retained
bytes are research evidence only; no production provider, source-use grant,
issuer policy or valuation input is authorized by that investigation.

Keep recurring current preparation and historical point-in-time availability
explicit. A structured provider may support current captured data while lacking
reproducible historical vintages. Report that limitation and retain the refusal
for an unsupported historical cutoff. A year in a filename, a series observation
date or today's capture cannot establish historical publication. New providers
must exercise the same source reproduction and policy boundaries in serving and
the release canary, including missing periods, conflicts and unsupported
versions.

## Maintained NYU workbooks

The [publisher's data catalog](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datacurrent.html)
links these stable annual download interfaces. The existing
`MarketReferenceProviderPort` reproduces their retained originals; serving and
the release canary use the same provider.

| Dataset | Supported download | Source profile |
| --- | --- | --- |
| U.S. industry unlevered beta | `pc/datasets/betas.xls` | `damodaran-us-unlevered-beta-xls-v1` |
| U.S. industry equity beta, borrowing cost and capital weights | `pc/datasets/wacc.xls` | `damodaran-us-industry-capital-xls-v1` |
| Country total ERP and tax reference | `pc/datasets/ctryprem.xlsx` | `damodaran-country-erp-tax-xlsx-v2` |

Download paths are relative to `https://pages.stern.nyu.edu/~adamodar/`.
The annual country workbook uses header row 8. Its explicit v2 profile retains
the mature-market and U.S. ERP methodology inputs, volatility adjustment and
any update annotation. It transcribes the published country total ERP in column
E; it does not substitute the CDS column H, a methodology input or a recomputed
number. Tax references retain their own lookup year. The existing archive
country v1 profile uses header row 7; neither profile guesses or falls back to
the other when a workbook changes.

These annual downloads do not promise the latest quarterly or monthly value.
Selection still checks the workbook's declared update date, maximum age,
issuer classification and source-use evidence. Capture time bounds availability;
an annotation cannot silently establish an earlier publication date. Retained
bytes and their digests identify a capture, because live URLs can change.
`free-market-source-use-v3` covers the revised country aggregate with the same
exact publisher permission evidence and attribution restrictions as v1.
Missing or changed permission bytes, raw-table redistribution and historical
cutoffs before capture still refuse.

The catalog's `histimpl.xls` annual series and the publisher's `ERPbymonth.xlsx`
monthly series are research candidates, without production adapters or grants.
They contain multiple ERP methodologies, including inputs from analyst growth
estimates. A historical observation in today's cumulative workbook establishes
neither its historical availability nor threshold ground truth.

## Extend a source

| Responsibility | Contract | Composition point |
| --- | --- | --- |
| Public request validation and capture availability | `PublicSourceCaptureProfilePort` | `PublicSourceAdapter(registrations=...)`; defaults live in `public_source_catalog.py`. |
| Reproduce a macro vintage from retained originals | `MacroSeriesProviderPort` | `create_app(macro_providers=...)` and the matching `DataReleaseCanaryRunner(macro_providers=...)`. |
| Reproduce country/industry reference rows | `MarketReferenceProviderPort` | `create_app(reference_providers=...)` and the matching canary `reference_providers`. |
| Reproduce a quote from retained source bytes | `QuoteSourceProviderPort` | The application's and canary's `quote_providers` parameters. |
| Reproduce original issuer classification | `IssuerClassificationProviderPort` | `reproduce_issuer_classification(provider, ...)`. |
| Map a classification to a reference subject | The industry/country crosswalk ports | `apply_industry_crosswalk` / `apply_country_crosswalk` with explicit provider/version/digest policy. |
| Replace SEC HTTP transport or accession-bound capture | `SecRequestTransportPort` / `SecSourceCapturePort` | `RetainedSecSourceAdapter`, SEC acquisition and ingestion constructors. |

Production defaults are assembled in `free_source_policy.py`,
`public_source_catalog.py`, `app.py` and the release command's composition root.
Runtime setup must supply the same approved provider set and source-use policy
to serving and the independent canary. No agent, UI, report or financial selector
should construct a provider client or interpret an upstream workbook/HTTP shape.

To add an alternative:

1. Implement the appropriate port. Validate the original source's identity,
   metric, population, unit, schema and availability evidence, then return the
   existing canonical vintage or observation contract. Retain missing cells and
   conflicts; do not fill them with defaults.
2. Register bounded request/capture behavior at the composition boundary. Keep
   HTTP, rate limits, retries and source formats in the adapter. Keep originals
   in the existing immutable content store and acquisition receipts.
3. Add a versioned `SourceUsePolicyV1` rule for the exact provider, metric,
   population, source profile, intended use, retained terms and required notices.
   A parser being installed does not grant permission to use its data. For
   example, ALFRED DGS10 parsing is implemented, but the default free-source
   policy currently has no ALFRED admission rule.
4. Supply a versioned issuer/time financial policy and compatible crosswalks.
   A different provider can reuse the same metric and selection policy. A new
   financial meaning, population or methodology requires its own explicit
   policy decision rather than a silent provider fallback.
5. Run the existing admission, selection, release and preparation boundaries with
   the alternative provider. Cover source tampering, wrong units/issuer/time,
   missing/conflicting rows, unchanged repeats and retained refusals. Existing
   JSON-provider substitution tests demonstrate these boundaries without an
   upstream network dependency.

## Availability, persistence and approval

The ordinary `fundamental-prepare-source --plan ... --plan-digest ...` command
can acquire required public originals before the existing SEC/release/forecast
flow. Add `public_sources` to its plan, with one entry per exact source:

```json
{
  "protocol": "public-source-acquisition-v1",
  "source_id": "damodaran-reference",
  "uri": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/ctryprem.xlsx",
  "source_profile": "damodaran-country-erp-tax-xlsx-v2",
  "terms_reference": "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/",
  "valuation_timestamp": "2026-11-13T12:00:00Z"
}
```

The timestamp must equal the plan's valuation timestamp. This example declares a
request; it does not assert that the mutable workbook existed at that cutoff.
The command uses `FUNDAMENTAL_PUBLIC_SOURCE_USER_AGENT` (or the configured SEC
contact), existing PostgreSQL metadata and content storage. Inject
`PublicSourceCapturePort` and the acquisition store/lock ports to use another
capture implementation. The profile is a downstream reproduction pin; declaring
its name does not establish that the captured bytes match it. Existing provider
reproduction and source admission must still validate them.

Canonical source/URI/profile/terms/valuation/protocol identity scopes each
receipt. Identical requests share a lock and reuse verified originals with
`wrote=false`, including after restart. Different valuation timestamps create
separate captures of mutable URLs. No issuer is included in the shared public
source identity. Corrupt receipts or originals refuse without refetch/repair;
current registration restrictions are checked before cache reuse. Receipt and
content stores perform the existing atomic writes. A crash after receipt commit
can resume without another download; a crash before that commit can require
another HTTP GET, without duplicate published records.

Every declared source's outcome appears in `public_source_outcomes`, including
failures and originals captured after the cutoff. A failed required source or
`SOURCE_NOT_AVAILABLE_AT_VALUATION` blocks preparation. Permanent provider
refusals are reused for that exact request. Retryable attempts retain their own
canonical evidence and permit a later retry; they are not completed captures.
A busy capture lease fails retryably before provider access. Invalid requests
and corrupted persistence fail at their boundary rather than becoming ordinary
provider failures.
The command returns exit 2 with canonical `source-preparation-error-v1` JSON on
stderr for source-plane exceptions. Its stable `code`, `retryable`, `plan_digest`
and optional `evidence_ref` let a caller distinguish a busy lease from a permanent
refusal without parsing message text.

This acquisition stage does not automatically create source-use admissions,
issuer crosswalks, market policies or trusted release candidates. The existing
selectors, evaluators and release canary remain required. Captured originals are
available through `retained_source` for those provider ports. Omitting
`public_sources` preserves existing SEC-only plans and their canonical digests.

Workbook filenames and observation dates do not prove historical availability.
The current Damodaran and mutable Treasury adapters bound availability by actual
capture time. Downloading an old annual table today cannot authorize its use at
an earlier valuation date. Dated vintage providers must reproduce their own
publication evidence. The same cutoff rule applies to every provider.

Acquisition reuses originals under the stable source scope. Canonical inputs,
source/mapping/model/policy versions and content digests identify derived
artifacts. Changing a provider or methodology creates a separately evidenced
selection; it never overwrites a prior artifact. A completed repeat returns the
existing result with `wrote=false`, including blocked/abstained results.

Automatic source-use admission, accounting mapping and market-policy approval
are separate executable decisions. Trusted machine signing binds those decisions
to the admitted evidence and deployment policy. The release canary reproduces
them before use. Missing or unsupported evidence still refuses. Authentic
caller approval remains bound to the exact prepared valuation input.

Neither a new provider nor automatic approval changes
`supported_history_threshold=null` or promotes provisional valuation quality.

## Publisher references

- [Damodaran data background and use](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datahistory.html) and [archived industry/country data](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/dataarchived.html).
- [U.S. Treasury interest-rate statistics](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics).
- [BEA historical data](https://apps.bea.gov/histdata/) and [BEA citation guidance](https://www.bea.gov/help/guidelines-for-citing-bea).
- [ALFRED](https://alfred.stlouisfed.org/) and [FRED terms](https://fred.stlouisfed.org/terms-of-use/); these links do not replace a deployment admission rule.
