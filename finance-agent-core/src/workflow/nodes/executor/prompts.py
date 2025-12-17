"""
Prompts for the Executor node.

These prompts will be used when integrating LLM-based parameter extraction.
"""

EXECUTOR_SYSTEM_PROMPT = """You are a financial analyst expert at extracting valuation parameters from financial documents.

Your task is to analyze financial statements, 10-K filings, and other documents to extract
the specific parameters needed for valuation models.

You must:
1. Extract accurate numerical data
2. Make reasonable assumptions when data is missing
3. Provide clear rationale for your choices
4. Return data in the exact schema format required
"""

SAAS_EXTRACTION_PROMPT = """Extract SaaS valuation parameters from the following financial data:

Ticker: {ticker}
Financial Documents: {documents}

Extract and return the following in JSON format:
- initial_revenue: Most recent annual revenue (in millions)
- growth_rates: 5-year projected revenue growth rates (as decimals)
- operating_margins: 5-year projected operating margins (as decimals)
- tax_rate: Effective tax rate (as decimal)
- da_rates: D&A as % of revenue for 5 years
- capex_rates: CapEx as % of revenue for 5 years
- wc_rates: Working capital change as % of revenue for 5 years
- sbc_rates: Stock-based compensation as % of revenue for 5 years
- wacc: Weighted average cost of capital (as decimal)
- terminal_growth: Terminal growth rate (as decimal)
- rationale: Brief explanation of key assumptions

Return ONLY valid JSON matching the schema.
"""

BANK_EXTRACTION_PROMPT = """Extract bank valuation parameters from the following financial data:

Ticker: {ticker}
Financial Documents: {documents}

Extract and return the following in JSON format:
- initial_net_income: Most recent annual net income (in millions)
- income_growth_rates: 5-year projected net income growth rates (as decimals)
- rwa_intensity: Return on Risk-Weighted Assets (as decimal)
- tier1_target_ratio: Target Tier 1 capital ratio (as decimal)
- initial_capital: Current Tier 1 capital (in millions)
- cost_of_equity: Cost of equity (as decimal)
- terminal_growth: Terminal growth rate (as decimal)
- rationale: Brief explanation of key assumptions

Return ONLY valid JSON matching the schema.
"""
