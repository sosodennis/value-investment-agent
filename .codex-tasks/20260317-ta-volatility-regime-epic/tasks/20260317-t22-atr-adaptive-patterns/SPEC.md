# Task Spec: T22 ATR-Adaptive Patterns

## Objective
Replace fixed pattern thresholds with ATR/ATRP-scaled thresholds and feed pattern runtime full OHLCV inputs.

## Scope
- Pass OHLC series into pattern runtime request construction.
- Make pattern detection compute volatility-aware thresholds from OHLC.
- Add targeted tests for low/high volatility behavior.

## Non-goals
- Regime classification.
- Volume profile / structure bins.
