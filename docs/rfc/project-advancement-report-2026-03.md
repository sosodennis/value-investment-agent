# RFC: Project Advancement Report 2026-03

Date: 2026-03-19
Status: Draft
Owner: Codex strategic synthesis

## Purpose

This document is the strategy synthesis report for the current project direction discussion.

It consolidates:

- the current RFC set under `docs/rfc`,
- the recent third-party architecture discussion,
- and external validation of enterprise-style practices.

Its purpose is to reduce directional ambiguity and give the project a single clear advancement recommendation.

## Inputs Reviewed

Primary local inputs:

- [technical-strategy-master-roadmap.md](/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfc/technical-strategy-master-roadmap.md)
- [technical-quant-feature-priorities-free-data.md](/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfc/technical-quant-feature-priorities-free-data.md)
- [calibration-upgrade-roadmap-and-roi.md](/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfc/calibration-upgrade-roadmap-and-roi.md)
- [Free-Data-Quant-Feature-Prioritization.md](/Users/denniswong/Downloads/Free-Data-Quant-Feature-Prioritization.md)

External validation references included:

- [yfinance docs](https://ranaroussi.github.io/yfinance/)
- [yfinance PriceHistory](https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html)
- [AQR Time Series Momentum](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)
- [Two Sigma Regime Modeling](https://www.twosigma.com/articles/a-machine-learning-approach-to-regime-modeling/)
- [Hudson & Thames Fractional Differentiation](https://hudsonthames.org/fractional-differentiation/)
- [Hudson & Thames MLFinLab](https://hudsonthames.org/mlfinlab/)
- [Alphalens](https://quantopian.github.io/alphalens/)
- [scikit-learn TimeSeriesSplit](https://scikit-learn.org/1.3/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)
- [NIST trustworthiness characteristics](https://airc.nist.gov/airmf-resources/airmf/3-sec-characteristics/)
- [Microsoft Appropriate Reliance](https://www.microsoft.com/en-us/research/articles/appropriate-reliance-research-initiative/)

## Executive Conclusion

The direction has **not** actually fragmented.

The current material already implies a coherent strategic line:

- the project should avoid opening too many new fronts at once,
- the next main axis should be to deepen the technical system,
- and that technical system should evolve from:

`classic indicators + limited quant`

into:

`deterministic signal + environment context + governed evidence layer`

This is the cleanest path that:

- matches the current architecture,
- fits the current free-data constraint,
- protects delivery speed,
- and preserves future extensibility.

The project should now treat the following as the formally adopted operating line:

- `Technical first`
- `Free-data-first`
- `Deterministic scoring first`
- `LLM for explanation only`
- `Evidence engine before macro expansion`
- `Calibration backbone before full calibration program`

## Main Recommendation

For the next major phase, the project should do **one main thing well**:

### Recommended near-term north star

Turn the technical system into the first mature deterministic evidence engine in the project.

This means:

1. keep classic technical indicators,
2. add a stronger quant context layer,
3. strengthen evidence, reliability, and projection semantics,
4. start building the data backbone needed for future calibration.

This also means explicitly **not** pushing all future ideas at once.

This is now a committed execution stance, not a brainstorming placeholder:

- `technical` is the primary growth surface,
- `macro` is future-compatible but not current critical path,
- `quant` should deepen context and reliability before it broadens into premium-data-only capability,
- `calibration` should begin with data collection and governance plumbing, not immediate probability-grade output.

## What Was Correct in the Third-Party Discussion

The external discussion was directionally strong in several important areas.

### 1. Free-data-first is the correct practical constraint

This is right.

For now, `yfinance`-style free data is strongest at:

- daily OHLCV,
- weekly OHLCV,
- limited intraday bars.

It is weak at:

- long-history intraday consistency,
- robust options surfaces,
- microstructure-quality data.

So a free-data-first technical roadmap is the correct engineering boundary.

### 2. Classic indicators should stay

This is also right.

Classic indicators such as:

- RSI
- MACD
- moving averages
- breakout state

should not be removed.

They should become the base signal generation layer.

### 3. Quant features should act as context, veto, and reliability inputs

This is strongly aligned with enterprise practice.

Quant features should not just become more buy/sell triggers.

They are more useful as:

- market-state descriptors,
- reliability modifiers,
- setup filters,
- evidence components for later synthesis.

### 4. LLM should not own runtime numeric scoring

This is also correct.

LLMs are appropriate for:

- explanation,
- structured narrative,
- categorical interpretation,
- debate context.

They are not the right owner for primary runtime numeric scoring or gating.

## Where The Discussion Needs Convergence

Several ideas from the discussion are valid, but should be demoted from "immediate roadmap" to "later capability."

### 1. Full research-stack evaluation is not the first priority

Walk-forward optimization, purged CV, and Alphalens-style evaluation are all valid concepts.

But they are not the first thing the project should build next.

The project should first strengthen:

- deterministic feature contracts,
- evidence structure,
- prediction-event collection,
- and reliability semantics.

Only after that should the project scale into a more complete research and validation stack.

### 2. Macro should not become a hard dependency yet

Macro is a legitimate future context provider.

But if it becomes a hard dependency right now for:

- fundamental,
- technical,
- news,
- debate,

then the project will open too many strategic fronts simultaneously.

The better approach is:

- define a future macro context contract,
- but do not make current progress depend on it.

### 3. Do not build a giant black-box composite score too early

The discussion around multipliers, vetoes, and contextual scoring is useful.

But the project should avoid collapsing everything into one giant opaque alpha score.

The better layered model is:

- classic signal
- context state
- veto and penalty logic
- reliability summary
- evidence bundle

## Formal Project Direction

### Fundamental

Fundamental should continue as a governed valuation system.

Near-term recommendation:

- do not significantly expand its scope,
- do not rush into full enterprise calibration,
- keep improving clarity, governance, and selective calibration maturity.

### Technical

Technical should become the first mature deterministic evidence engine in the project.

This is the most practical and highest-ROI strategic path right now.

### Macro

Macro should be defined as a future optional context provider.

It should not become a hard upstream dependency in the immediate roadmap.

### Calibration

Calibration should first be treated as a governed data backbone problem:

- prediction events,
- delayed outcomes,
- dataset construction,
- later offline fitting and monitoring.

Do not chase full probability-grade enterprise calibration immediately.

## The Next 90 Days

The project should focus on only four major objectives.

### 1. Add the technical P1 quant layer

Near-term recommended `P1 core` families:

- volatility regime
- liquidity proxy
- normalized distance
- cross-timeframe alignment

Secondary additions for later in the same window if capacity remains:

- persistence
- structural break

These should be treated as `P1.5 / early P2`, not co-equal with the P1 core.

Breadth should also be split into two future paths:

- `small-scope breadth pilot` can be explored later using a tightly scoped watchlist or sector subset,
- `platform-level breadth` should wait until broader universe orchestration and data completeness are stronger.

### 2. Institutionalize the relationship between classic and quant

Recommended semantics:

- classic = base directional signal
- quant = context, veto, reliability, evidence
- LLM = explanation only

This rule should become explicit and durable.

### 3. Build the technical prediction-event and outcome-labeling backbone

This should begin now, even before a full calibration program exists.

The goal is to lay the data foundation for:

- future calibration,
- future backtesting discipline,
- future evaluation maturity.

### 4. Keep contracts provider-agnostic

The project may rely on free data now, but feature contracts should not be coupled directly to Yahoo-specific assumptions.

This preserves future optionality without forcing premium data today.

## What Not To Do Now

The project should explicitly avoid doing the following in the current phase:

- making macro a hard dependency,
- prioritizing options-implied or microstructure features,
- letting LLMs own runtime numeric scoring,
- upgrading fundamental calibration into a full enterprise program,
- building a giant composite alpha score too early.

## Technical Architecture Judgment

The strongest architecture line right now is:

### 1. Technical Classic Layer

Examples:

- RSI
- MACD
- moving averages
- breakout state

Role:

- base directional signal generation

### 2. Technical Quant Context Layer

Examples:

- volatility regime
- liquidity proxy
- normalized distance
- cross-timeframe alignment

Role:

- market context
- vetoes
- penalties
- reliability inputs

### 3. Evidence and Projection Layer

Role:

- unify signal, context, quality, alerts, and readouts

Important note:

- this layer is already partially built in the current system,
- so it is the correct place to deepen next.

### 4. Calibration Data Backbone

Role:

- prediction events
- delayed outcomes
- dataset construction
- future offline fit and monitoring

This should be treated as a governed data and evaluation layer, not an immediate UI feature.

This route should remain more important than:

- early macro expansion,
- premium-only quant surface area,
- and large black-box composite scoring.

## Primary Risk

The main risk right now is not insufficient sophistication.

The main risk is **scope expansion without sequencing discipline**.

If the project simultaneously pushes:

- more quant features,
- macro,
- full calibration,
- broader agent dependencies,
- premium-data-ready expansion,

then progress will fragment and quality will decline.

## Decisions That Should Be Formally Locked

The project should explicitly lock these three decisions:

1. **H1 2026 mainline is technical, not macro**
2. **TA runtime numeric logic belongs to deterministic backend, not LLM**
3. **Quant roadmap stays inside free-data-compatible P1 families before premium-only features**

Operationally, those three decisions should be read together with the adopted six-line policy at the top of this document rather than as isolated guidance.

## Operating Slogan

If the team wants one concise execution phrase, it should be:

**Go deeper on the technical evidence engine before going broader on macro and full calibration.**

## Relationship To Other RFCs

This document is the top-level strategy synthesis for the current expansion debate.

Recommended follow-on reading:

1. [technical-strategy-master-roadmap.md](/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfc/technical-strategy-master-roadmap.md)
2. [technical-quant-feature-priorities-free-data.md](/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfc/technical-quant-feature-priorities-free-data.md)
3. [calibration-upgrade-roadmap-and-roi.md](/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfc/calibration-upgrade-roadmap-and-roi.md)

Interpretation:

- this report is the executive decision memo,
- the master roadmap is the structured entry point,
- the quant RFC is the feature-expansion annex,
- the calibration RFC is the governance and evaluation annex.
