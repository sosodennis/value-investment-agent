# RFC: Technical Quant Feature Priorities Under Free-Data Constraints

Date: 2026-03-18
Status: Supporting Annex
Owner: Codex working notes for future technical roadmap planning

## Document Role

This file is a **supporting annex** to the master roadmap:

- [technical-strategy-master-roadmap.md](/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfc/technical-strategy-master-roadmap.md)

Primary purpose:

- define which technical quant feature families should be prioritized under free-data constraints,
- and clarify future extensibility toward stronger data providers.

Dependency note:

- this RFC should be read **after** the master roadmap,
- and **before** the calibration RFC,
- because it defines the feature surface that future calibration work would need to evaluate and govern.

Read order:

1. [project-advancement-report-2026-03.md](/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfc/project-advancement-report-2026-03.md)
2. [technical-strategy-master-roadmap.md](/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfc/technical-strategy-master-roadmap.md)
3. [technical-quant-feature-priorities-free-data.md](/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfc/technical-quant-feature-priorities-free-data.md)
4. [calibration-upgrade-roadmap-and-roi.md](/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfc/calibration-upgrade-roadmap-and-roi.md)

## Summary

This RFC evaluates which additional `quant` features are worth introducing into the current technical system, under the practical assumption that the project primarily depends on free market-data sources such as `yfinance`.

Main conclusion:

- with `yfinance`-style free data, the most practical next layer is still `daily/weekly/intraday-lite OHLCV quant`,
- the best `P1 core` additions are `volatility`, `liquidity-proxy`, `normalized distance`, and `cross-timeframe alignment`,
- `persistence` and `structural-break` remain attractive, but should be treated as `P1.5 / early P2` rather than co-equal P1 anchors,
- `options-implied`, `market breadth`, and especially `microstructure` should be designed for future extensibility, but not treated as near-term core dependencies,
- `fractional differencing` is useful, but too narrow to act as the project’s only quant identity.

This RFC should now be read under the formally adopted project stance:

- `Technical first`
- `Free-data-first`
- `Deterministic scoring first`
- `LLM for explanation only`
- `Evidence engine before macro expansion`
- `Calibration backbone before full calibration program`

## Why This RFC Exists

The current technical stack already includes `fractional differencing`-oriented quant logic, but real enterprise technical and quant systems usually incorporate a broader, layered feature surface.

The main product question is not "what is academically interesting?"

It is:

- what can be built now with free data,
- what is worth the engineering complexity,
- and how should the system remain extensible for future premium data sources.

## External Validation Summary

The prioritization in this RFC was checked against public documentation and institutional research:

- `yfinance` supports long-history `1d/1wk/1mo` bars and intraday intervals, but intraday history is limited to the last 60 days according to the current docs.
  Source: [yfinance PriceHistory](https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html), [yfinance download docs](https://ranaroussi.github.io/yfinance/reference/yfinance.functions.html)

- `yfinance` is an open-source Yahoo wrapper intended for research/personal use and should not be treated as a stable institutional market-data foundation.
  Source: [yfinance documentation](https://ranaroussi.github.io/yfinance/)

- fractional differentiation is widely used in financial machine learning as one feature-engineering tool among many, not as a complete quant stack.
  Source: [Hudson & Thames on Fractional Differentiation](https://hudsonthames.org/fractional-differentiation/), [MlFinPy Fractional Differentiated docs](https://mlfinpy.readthedocs.io/en/stable/FractionalDifferentiated.html)

- enterprise quant research heavily uses additional families such as trend/momentum, factors, regimes, and risk-state analysis.
  Source: [AQR Time Series Momentum](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum), [AQR Factor Momentum Everywhere](https://www.aqr.com/Insights/Research/Working-Paper/Factor-Momentum-Everywhere), [Two Sigma Regime Modeling](https://www.twosigma.com/articles/a-machine-learning-approach-to-regime-modeling/)

- more advanced microstructure features exist, but many require tick or richer intraday data, which is not a good match for a `yfinance-first` architecture.
  Source: [MlFinLab 0.5.2 release notes](https://hudsonthames.org/mlfinlab-0-5-2-release-notes/)

## Constraints Assumed in This RFC

Current practical constraints:

- primary data source is free and Yahoo-like,
- long-history daily and weekly bars are available,
- intraday bars are available but with restricted historical depth,
- options history quality and coverage are not strong enough to anchor the core roadmap,
- tick data, order book data, and robust universe-level breadth datasets are not assumed.

This means any feature family that depends on:

- stable options surfaces,
- tick-level trades,
- order book imbalance,
- or broad institutional universe datasets

should be treated as future-extensible, not near-term-core.

## Priority Matrix

| Feature Family | Typical Examples | Product Value | Data Acquisition Difficulty with Free Sources | Implementation Complexity | Recommended Priority |
|---|---|---:|---:|---:|---|
| Volatility Regime | realized vol, downside vol, vol percentile, expansion/compression | High | Low | Low-Medium | `P1` |
| Persistence / Mean Reversion | Hurst proxy, rolling autocorrelation, half-life style indicators | High | Low | Medium | `P1.5` |
| Structural Break / State Shift | SADF-style proxy, variance shift, break score | High | Low | Medium | `P1.5` |
| Liquidity Proxy | Amihud-like illiquidity, turnover stress, dollar-volume regime | High | Low | Low-Medium | `P1` |
| Normalized Distance | price vs MA z-score, ATR-normalized displacement, return z-score | Medium-High | Low | Low | `P1` |
| Cross-Timeframe Alignment | 1d/1wk agreement, trend confirmation, vol-state agreement | High | Low | Medium | `P1` |
| Volume Structure Quant | OBV variants, surge percentile, accumulation/distribution refinements | Medium-High | Low | Medium | `P2` |
| Event / Gap Quant | gap continuation or reversion features, post-event drift proxy | Medium-High | Medium | Medium | `P2` |
| Cross-Sectional Breadth | sector breadth, dispersion, relative strength vs market | High | Medium-High | Medium-High | `Pilot-Later` |
| Options-Implied Quant | implied vol, skew, term structure, IV/RV spread | High | High | Medium-High | `P3` |
| Intraday Microstructure | VPIN, order-flow imbalance, Roll/Kyle/Hasbrouck intraday | High | Very High | High | `P3` |
| Alternative Data Quant | sentiment feed, web traffic, supply chain, app usage | Variable | Very High | High | `Later` |

## Reconsidered Data Difficulty Under yfinance-First Assumptions

The original generic ranking needs one important adjustment:

- free-source difficulty is not just about whether a formula can be computed,
- it is about whether the data can be collected consistently, historically, and safely enough for product use.

### What is genuinely easy with yfinance-like free data

These are good fits for the current stack:

- daily and weekly realized volatility
- rolling volatility percentiles
- downside volatility
- ATR-normalized displacement
- rolling return z-scores
- turnover and dollar-volume proxies
- daily-bar liquidity proxies
- persistence and mean-reversion diagnostics based on returns or close prices
- cross-timeframe consistency features using `1d` and `1wk`

Why:

- they depend mostly on long-history OHLCV,
- they are robust to limited intraday depth,
- they fit the current technical architecture well.

### What is possible but should be handled cautiously

- `1h`-based short-horizon features
- gap and event features
- intraday-lite volatility state features

Why caution is needed:

- `yfinance` intraday history is limited,
- the project has already seen degraded cases where `1h` is unavailable,
- these features are still worth building, but should be explicitly quality-gated.

### What should not anchor the near-term roadmap

- options-implied signals
- true microstructure signals
- order-flow imbalance
- robust breadth and dispersion across large universes

Why:

- the data requirements are not aligned with a free-source-first architecture,
- historical depth and consistency are weaker,
- long-term maintainability is poor unless a better vendor is introduced.

## Recommended Near-Term Quant Stack

### Tier 1: Build now with current data

These are the best next additions.

#### 1. Volatility regime

Examples:

- rolling realized volatility
- downside volatility
- volatility percentile
- volatility expansion/compression score

Why it is worth it:

- directly improves `risk`, `regime`, and `setup reliability`
- highly usable in UI and evidence summaries
- strong fit with free OHLCV data

#### 2. Liquidity proxy

Examples:

- Amihud-style illiquidity
- turnover stress
- dollar-volume regime

Why it is worth it:

- gives a better answer to "should we trust this setup?"
- very useful for enterprise-style evidence and reliability surfaces
- still feasible using only OHLCV and volume

#### 3. Normalized distance features

Examples:

- price-vs-trend z-score
- ATR-normalized move
- vol-adjusted dislocation

Why it is worth it:

- cheap to build
- very interpretable in UI
- useful in evidence, alerts, and explainers

#### 4. Cross-timeframe alignment quant

Examples:

- 1d and 1wk trend agreement
- 1d and 1wk vol-state agreement
- alignment or disagreement score

Why it is worth it:

- excellent fit with the current multi-timeframe technical system
- helps improve fusion quality and reliability explanations

### Tier 1.5: Build after the P1 core is stable

These are still good fits, but they should not crowd the first implementation wave.

#### 5. Persistence / mean-reversion diagnostics

Examples:

- rolling autocorrelation
- Hurst-like persistence proxy
- half-life-style mean-reversion proxy

Why it is worth it:

- pairs naturally with existing fractional-differencing logic
- gives more intuitive "trend memory vs snap-back risk" evidence

#### 6. Structural-break features

Examples:

- break score
- volatility-state shift
- trend breakdown risk proxy

Why it is worth it:

- strong for detecting setup invalidation and state changes
- high product value for interpretation and alerts

### Tier 2: Good next, but not first

#### 7. Volume structure refinements

Examples:

- OBV-derived diagnostics
- volume surprise percentile
- refined accumulation/distribution state

Why:

- valuable, but less foundational than volatility or liquidity

#### 8. Event / gap quant

Examples:

- overnight gap continuation/reversion
- post-event drift proxy

Why:

- useful, but label semantics and event definition need more care

### Tier 3: Design for later, do not anchor current roadmap

#### 9. Options-implied quant

Examples:

- implied vol
- skew
- IV term structure
- IV/RV spread

Why later:

- strong product value, but poor fit for current free-source constraints
- should remain a future extension point

#### 10. Intraday microstructure

Examples:

- VPIN
- Roll measure
- Kyle lambda
- order-flow imbalance

Why later:

- rich academically and practically,
- but usually wants better intraday granularity and stability than current free-source assumptions provide

#### 11. Breadth and market-relative quant

Examples:

- sector breadth
- dispersion
- relative strength to market or sector

Why later:

- useful, but needs broader universe collection and orchestration
- a small watchlist or sector-scoped breadth pilot can precede a true platform-level breadth build

## Enterprise-Like Design Guidance

The system should remain extensible even if the immediate roadmap is free-data-first.

Recommended design principle:

- separate `feature semantics` from `data provider specifics`

This means:

1. define feature contracts in a provider-agnostic way,
2. tag each feature with input-basis and fidelity,
3. let the runtime degrade gracefully when the required data is unavailable,
4. keep room for better providers later without redesigning the consumer surface.

### Good extensibility pattern

For each future quant family, define:

- `feature_code`
- `required_inputs`
- `source_fidelity`
- `quality_flags`
- `warmup_requirements`
- `calculation_version`

Then the same feature slot can later be backed by:

- Yahoo/free OHLCV
- paid OHLCV provider
- options vendor
- intraday or tick vendor

without rewriting the report/UI contract.

## Suggested Architecture Implications

### Build now

- add new quant features that rely on `1d / 1wk / 1h-lite OHLCV`
- make fidelity explicit for intraday-derived features
- keep feature contracts additive and typed

### Avoid now

- hard-coding features that assume premium-only inputs
- mixing experimental premium-data semantics into the same feature name
- treating low-depth free intraday data as institutional-grade microstructure data

## Practical Recommendation

The recommended build order is:

1. volatility regime
2. liquidity proxy
3. normalized distance features
4. cross-timeframe alignment
5. persistence / mean-reversion diagnostics
6. structural-break features
7. volume structure refinements

And after that:

- reassess whether `breadth`, `options-implied`, or `microstructure` are worth introducing based on actual vendor strategy.

## Final Position

Under a `yfinance`-first constraint, the best enterprise-like move is not to chase the most advanced quant formulas.

It is to:

- strengthen the `daily-ohlcv-first quant layer`,
- expose feature quality and fidelity clearly,
- and design the contracts so that better data can be plugged in later.

This preserves both delivery speed and future extensibility.
