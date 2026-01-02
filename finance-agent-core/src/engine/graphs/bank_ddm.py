from ..core import CalculationGraph


def project_net_income(
    initial_net_income: float, income_growth_rates: list[float]
) -> list[float]:
    income = []
    current = initial_net_income
    for g in income_growth_rates:
        current = current * (1 + g)
        income.append(current)
    return income


def calculate_rwa(net_income: list[float], rwa_intensity: float) -> list[float]:
    # Simplified: RWA proportional to Income? Or usually RWA grows with Loan Book.
    # Let's assume RWA grows at same rate + some factor, or driven by Asset Growth.
    # If we only have income growth, we assume Assets grow roughly w/ Income.
    # RWA = (Net Income / RoRWA)
    # This is a circular dependency if RoRWA is input.
    # Let's assume RoRWA (Return on RWA) is constant or input list.
    return [ni / rwa_intensity for ni in net_income]  # rwa_intensity = RoRWA


def calculate_required_capital(
    rwa: list[float], tier1_target_ratio: float
) -> list[float]:
    return [r * tier1_target_ratio for r in rwa]


def calculate_dividends(
    net_income: list[float], required_capital: list[float], initial_capital: float
) -> list[float]:
    # Dividends = Net Income - Change in Required Capital
    divs = []
    prev_cap = initial_capital

    for i, ni in enumerate(net_income):
        req_cap = required_capital[i]
        delta_cap = req_cap - prev_cap

        # If delta_cap is positive (we need more capital), we retain earnings.
        # Div = NI - Retained Earnings
        # Retained Earnings = Delta Cap

        d = ni - delta_cap

        # Bank regulator constraint: Div cannot be negative (usually implies equity raise, but DDM assumes payouts).
        # We allow negative for valuation (implies dilution/infusion).
        divs.append(d)
        prev_cap = req_cap

    return divs


def calculate_pv(
    dividends: list[float], cost_of_equity: float, terminal_growth: float
) -> float:
    # PV of Dividends + Terminal Value
    pv = 0.0
    for t, d in enumerate(dividends):
        pv += d / ((1 + cost_of_equity) ** (t + 1))

    last_div = dividends[-1]
    tv = (last_div * (1 + terminal_growth)) / (cost_of_equity - terminal_growth)

    last_period = len(dividends)
    pv_tv = tv / ((1 + cost_of_equity) ** last_period)

    return pv + pv_tv


def create_bank_graph() -> CalculationGraph:
    graph = CalculationGraph("Bank_DDM")

    # Inputs: initial_net_income, income_growth_rates, rwa_intensity (RoRWA), tier1_target_ratio, initial_capital, cost_of_equity, terminal_growth

    graph.add_node("net_income", project_net_income)

    # calculate_rwa(net_income, rwa_intensity)
    graph.add_node("rwa", calculate_rwa)

    # calculate_required_capital(rwa, tier1_target_ratio)
    graph.add_node("required_capital", calculate_required_capital)

    # calculate_dividends(net_income, required_capital, initial_capital)
    graph.add_node("dividends", calculate_dividends)

    # calculate_pv(dividends, cost_of_equity, terminal_growth)
    graph.add_node("equity_value", calculate_pv)

    return graph
