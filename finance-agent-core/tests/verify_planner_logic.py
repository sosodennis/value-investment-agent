"""
Simple verification script for Planner Node logic.

This script tests the model selection logic without requiring full dependencies.
Run this to verify the GICS-based model selection rules.
"""

# Mock the structures for standalone testing
class ValuationModel:
    DCF_GROWTH = "dcf_growth"
    DCF_STANDARD = "dcf_standard"
    DDM = "ddm"
    FFO = "ffo"
    EV_REVENUE = "ev_revenue"
    EV_EBITDA = "ev_ebitda"


class CompanyProfile:
    def __init__(self, ticker, name, sector=None, industry=None, is_profitable=None):
        self.ticker = ticker
        self.name = name
        self.sector = sector
        self.industry = industry
        self.is_profitable = is_profitable


def select_valuation_model(profile):
    """
    Simplified version of the model selection logic for testing.
    """
    sector = (profile.sector or "").lower()
    industry = (profile.industry or "").lower()
    
    # Rule 1: Banks -> DDM
    if "financial" in sector or "bank" in industry:
        if "bank" in industry:
            return (ValuationModel.DDM, "Banking sector: Using DDM")
    
    # Rule 2: REITs -> FFO
    if "real estate" in sector or "reit" in industry:
        return (ValuationModel.FFO, "REIT: Using FFO model")
    
    # Rule 3: Utilities -> DDM
    if "utilities" in sector:
        return (ValuationModel.DDM, "Utilities: Using DDM")
    
    # Rule 4: Technology
    if "technology" in sector:
        if profile.is_profitable is False or "software" in industry:
            return (ValuationModel.DCF_GROWTH, "High-growth tech: Using DCF Growth")
        else:
            return (ValuationModel.DCF_STANDARD, "Mature tech: Using Standard DCF")
    
    # Rule 5: Consumer/Auto
    if "consumer" in sector or "cyclical" in sector:
        if "auto" in industry or "vehicle" in industry:
            return (ValuationModel.DCF_GROWTH, "Auto/EV: Using DCF Growth")
        else:
            return (ValuationModel.DCF_STANDARD, "Consumer: Using Standard DCF")
    
    # Default
    return (ValuationModel.DCF_STANDARD, "Default: Using Standard DCF")


def run_tests():
    """Run verification tests."""
    print("="*70)
    print("PLANNER NODE VERIFICATION TESTS")
    print("="*70)
    
    test_cases = [
        {
            "name": "JPMorgan (Bank)",
            "profile": CompanyProfile("JPM", "JPMorgan", "Financial Services", "Banks"),
            "expected": ValuationModel.DDM
        },
        {
            "name": "Tesla (Auto/EV)",
            "profile": CompanyProfile("TSLA", "Tesla", "Consumer Cyclical", "Auto Manufacturers"),
            "expected": ValuationModel.DCF_GROWTH
        },
        {
            "name": "American Tower (REIT)",
            "profile": CompanyProfile("AMT", "American Tower", "Real Estate", "REIT - Specialty"),
            "expected": ValuationModel.FFO
        },
        {
            "name": "NextEra Energy (Utility)",
            "profile": CompanyProfile("NEE", "NextEra", "Utilities", "Utilities - Renewable"),
            "expected": ValuationModel.DDM
        },
        {
            "name": "Apple (Mature Tech)",
            "profile": CompanyProfile("AAPL", "Apple", "Technology", "Consumer Electronics", is_profitable=True),
            "expected": ValuationModel.DCF_STANDARD
        }
    ]
    
    passed = 0
    failed = 0
    
    for test in test_cases:
        model, reasoning = select_valuation_model(test["profile"])
        
        if model == test["expected"]:
            status = "✓ PASS"
            passed += 1
        else:
            status = "✗ FAIL"
            failed += 1
        
        print(f"\n{status} - {test['name']}")
        print(f"  Sector: {test['profile'].sector}")
        print(f"  Industry: {test['profile'].industry}")
        print(f"  Expected: {test['expected']}")
        print(f"  Got: {model}")
        print(f"  Reasoning: {reasoning}")
    
    print("\n" + "="*70)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(test_cases)} tests")
    print("="*70)
    
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
