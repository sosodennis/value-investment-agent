# Planner Node - README

## Overview
The Planner Node is the first stage in the Value Investment Agent workflow. It resolves user queries to stock tickers and automatically selects the appropriate valuation model based on company sector and industry.

## Quick Start

### Installation
```bash
cd finance-agent-core
pip install -e .
```

### Optional: Install OpenBB
```bash
pip install openbb
```
*Note: The planner works without OpenBB using mock data for testing.*

### Basic Usage

```python
from workflow.graph import graph

# Initialize state
state = {
    "ticker": "TSLA",  # or "Tesla" for search
    "model_type": None
}

# Run the planner
result = graph.invoke(state)

print(result["planner_output"])
# Output:
# {
#   "company_name": "Tesla Inc",
#   "sector": "Consumer Cyclical",
#   "industry": "Auto Manufacturers",
#   "selected_model": "dcf_growth",
#   "reasoning": "Automotive/EV manufacturer: Capital-intensive..."
# }
```

## Model Selection Rules

The planner automatically selects models based on GICS sectors:

| Company Type | Model | Example |
|--------------|-------|---------|
| Banks | DDM (Dividend Discount) | JPMorgan (JPM) |
| REITs | FFO (Funds From Operations) | American Tower (AMT) |
| Utilities | DDM | NextEra Energy (NEE) |
| High-Growth Tech | DCF Growth | Tesla (TSLA) |
| Mature Tech | DCF Standard | Apple (AAPL) |

## Testing

### Run Verification Tests
```bash
python finance-agent-core/tests/verify_planner_logic.py
```

### Run Full Test Suite (requires pytest)
```bash
pytest finance-agent-core/tests/test_planner_node.py -v
```

## Architecture

```
planner/
├── structures.py   # Data models (Pydantic)
├── tools.py        # OpenBB integration
├── logic.py        # Model selection rules
└── node.py         # Main orchestration
```

## Configuration

### OpenBB API Keys
Create a `.env` file:
```bash
# Optional: For premium data providers
FMP_API_KEY=your_key_here
POLYGON_API_KEY=your_key_here
```

### Supported Providers
- **Free**: Yahoo Finance (yfinance)
- **Paid**: Financial Modeling Prep (FMP), Polygon.io, Intrinio

## Next Steps

1. **Install OpenBB**: `pip install openbb`
2. **Configure API Keys**: Add to `.env` file
3. **Test with Real Data**: Run with actual tickers
4. **Integrate HITL**: Add LangGraph interruption for ambiguous queries

## Documentation

- [Implementation Plan](../../../.gemini/antigravity/brain/cd70a55e-fa9b-4747-b587-43ec08b61d3f/implementation_plan.md)
- [Walkthrough](../../../.gemini/antigravity/brain/cd70a55e-fa9b-4747-b587-43ec08b61d3f/walkthrough.md)
- [Research Documents](../../../research-planner-0.md)

## Support

For issues or questions, refer to:
- OpenBB Documentation: https://docs.openbb.co
- Project AGENTS.md for agent responsibilities
