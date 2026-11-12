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
