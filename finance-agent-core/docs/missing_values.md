# Missing Values (Post-XBRL Derivation)

## Scope
This document lists values that are **not available directly from SEC XBRL** and remain missing after
applying all XBRL-derived computations in the Fundamental Analysis pipeline.

## Global Missing Values (Non-XBRL)
These values require **market data providers** or **manual policy assumptions**:
- `current_price`
- `market_cap`
- `enterprise_value` (if derived from market cap + debt/cash, needs market cap)
- `beta`
- `risk_free_rate`
- `equity_risk_premium`
- `terminal_growth`

## Model-Specific Missing Values
### SaaS DCF (FCFF)
- `wacc`
- `terminal_growth`

### Bank DDM
- `cost_of_equity`
- `terminal_growth`

### EV/Revenue
- `ev_revenue_multiple`

### EV/EBITDA
- `ev_ebitda_multiple`

### REIT FFO
- `ffo_multiple`

### Residual Income
- `projected_residual_incomes`
- `required_return`
- `terminal_growth`

### EVA
- `projected_evas`
- `wacc`
- `terminal_growth`

## XBRL Coverage Gaps (Conditional)
These values **can be XBRL-sourced**, but may be missing depending on company filings or taxonomy usage:
- `shares_outstanding`
- `total_debt`
- `cash_and_equivalents`
- `operating_income`
- `income_before_tax`
- `depreciation_and_amortization`
- `share_based_compensation`
- `capex`
- `ffo` (computed; requires net income, D&A, gains on sale)
- `rwa_intensity` / `tier1_target_ratio` (financial institutions)

## Notes
- All missing values are surfaced in `fundamental_analysis.missing_inputs` when running calculations.
- No mock data is used.
- XBRL-derived fields (ROIC, NOPAT, working capital delta, reinvestment rate, etc.) are computed where possible.
