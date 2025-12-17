from typing import List
from pydantic import Field
from .._template.schemas import BaseValuationParams

class BankParams(BaseValuationParams):
    initial_net_income: float = Field(..., description="Most recent annual Net Income (in millions)")
    income_growth_rates: List[float] = Field(..., description="Projected Net Income growth rates")
    rwa_intensity: float = Field(..., description="RoRWA (Return on Risk Weighted Assets) or Income/RWA ratio. Used to project RWA growth.")
    tier1_target_ratio: float = Field(..., description="Target Tier 1 Capital Ratio (e.g., 0.12)")
    initial_capital: float = Field(..., description="Current Tier 1 Capital")
    cost_of_equity: float = Field(..., description="Cost of Equity (Ke)")
    terminal_growth: float = Field(..., description="Terminal growth rate")
