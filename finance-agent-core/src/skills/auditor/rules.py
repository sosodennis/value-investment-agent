from typing import List, Union, Dict
from ..valuation_saas.schemas import SaaSParams
from ..valuation_bank.schemas import BankParams

class AuditResult:
    def __init__(self, passed: bool, messages: List[str]):
        self.passed = passed
        self.messages = messages

def audit_saas_params(params: SaaSParams) -> AuditResult:
    messages = []
    
    # Rule 1: Terminal Growth
    if params.terminal_growth > 0.04:
        messages.append(f"FAIL: Terminal growth {params.terminal_growth} exceeds 4% GDP cap.")
    
    # Rule 2: WACC
    if params.wacc < 0.05:
        messages.append(f"FAIL: WACC {params.wacc} is unrealistically low (< 5%).")
        
    # Rule 3: SBC Check
    if all(s == 0 for s in params.sbc_rates):
        messages.append("WARN: SBC rates are all 0%. This is unusual for SaaS.")
        
    passed = len([m for m in messages if "FAIL" in m]) == 0
    return AuditResult(passed, messages)

def audit_bank_params(params: BankParams) -> AuditResult:
    messages = []
    
    if params.terminal_growth > 0.04:
         messages.append(f"FAIL: Terminal growth {params.terminal_growth} exceeds 4% GDP cap.")
         
    if params.cost_of_equity < 0.06:
        messages.append(f"FAIL: Cost of Equity {params.cost_of_equity} is too low.")
        
    passed = len([m for m in messages if "FAIL" in m]) == 0
    return AuditResult(passed, messages)
