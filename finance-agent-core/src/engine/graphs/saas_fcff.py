from ..core import CalculationGraph


def project_revenue(initial_revenue: float, growth_rates: list[float]) -> list[float]:
    revenue = []
    current = initial_revenue
    for g in growth_rates:
        current = current * (1 + g)
        revenue.append(current)
    return revenue


def calculate_ebit(revenue: list[float], operating_margins: list[float]) -> list[float]:
    return [r * m for r, m in zip(revenue, operating_margins, strict=False)]


def calculate_nopat(ebit: list[float], tax_rate: float) -> list[float]:
    return [e * (1 - tax_rate) for e in ebit]


def calculate_fcff(
    nopat: list[float],
    revenue: list[float],
    da_rates: list[float],
    capex_rates: list[float],
    wc_rates: list[float],
    sbc_rates: list[float],
) -> list[float]:
    # FCFF = NOPAT + D&A - CapEx - DeltaWC + SBC (if treating SBC as non-cash add-back)
    # DeltaWC calculation needs previous period. For simplicity here, we assume WC is a % of Revenue
    # and DeltaWC approx = CurrentWC - PrevWC.
    # We will approximate DeltaWC = Revenue * WC_Rate * Growth_Rate?
    # Or just Delta Revenue * WC_Rate.

    fcff = []
    # prev_rev = revenue[0] / (1 + 0.1)  # Hack for first period delta? Or pass initial.
    # Actually, let's assume `revenue` list implies the years.

    # Needs sophisticated logic for accurate delta WC, but let's keep it simple for the prototype.
    # Cash Flow = NOPAT + (Rev*DA) - (Rev*CapEx) - (DeltaRev * WC) + (Rev*SBC)

    for i, _ in enumerate(revenue):
        r = revenue[i]
        n = nopat[i]

        da = r * da_rates[i]
        capex = r * capex_rates[i]
        sbc = r * sbc_rates[i]

        # Delta WC approximation
        if i == 0:
            delta_rev = r * 0.1  # Assumption
        else:
            delta_rev = r - revenue[i - 1]

        delta_wc = delta_rev * wc_rates[i]

        f = n + da - capex - delta_wc + sbc
        fcff.append(f)
    return fcff


def calculate_terminal_value(
    final_fcff: float, wacc: float, terminal_growth: float
) -> float:
    # TV = FCFF_n+1 / (WACC - g)
    # FCFF_n+1 = Final_FCFF * (1+g)
    return (final_fcff * (1 + terminal_growth)) / (wacc - terminal_growth)


def calculate_pv(fcff: list[float], terminal_value: float, wacc: float) -> float:
    pv = 0.0
    for t, cash_flow in enumerate(fcff):
        discount_factor = (1 + wacc) ** (t + 1)
        pv += cash_flow / discount_factor

    # Add TV PV
    last_period = len(fcff)
    pv += terminal_value / ((1 + wacc) ** last_period)
    return pv


def create_saas_graph() -> CalculationGraph:
    graph = CalculationGraph("SaaS_FCFF")

    # Input Nodes (implicit in function signatures, but can be explicit if needed)
    # Nodes: initial_revenue, growth_rates, operating_margins, tax_rate, da_rates, capex_rates, wc_rates, sbc_rates, wacc, terminal_growth

    graph.add_node("projected_revenue", project_revenue)
    graph.add_node("ebit", calculate_ebit)
    # Note: calculate_ebit takes (revenue, operating_margins).
    # But graph node name is "projected_revenue".
    # The param name in calculate_ebit is 'revenue'.
    # We need to map 'projected_revenue' -> 'revenue' or rename functions/variables.
    # For simplicity in this `CalculationGraph` implementation, names must match exactly.
    # So we need to alias inputs or ensure function arg names match node names.

    # Let's fix names in functions or graph wrapper.
    # Or strict naming convention.

    # To fix this, I will rename the function signature in `calculate_ebit` to match the node `projected_revenue`?
    # Or usage: project_revenue(initial_revenue, growth_rates) -> produces 'revenue'
    # So I should name the node "revenue".

    graph.add_node("revenue", project_revenue)

    # calculate_ebit(revenue, operating_margins)
    graph.add_node("ebit", calculate_ebit)

    # calculate_nopat(ebit, tax_rate)
    graph.add_node("nopat", calculate_nopat)

    # calculate_fcff(nopat, revenue, da_rates, capex_rates, wc_rates, sbc_rates)
    graph.add_node("fcff", calculate_fcff)

    # Wrapper for TV to take specific element
    def get_final_fcff(fcff: list[float]) -> float:
        return fcff[-1]

    graph.add_node("final_fcff", get_final_fcff)

    # calculate_terminal_value(final_fcff, wacc, terminal_growth)
    graph.add_node("terminal_value", calculate_terminal_value)

    # calculate_pv(fcff, terminal_value, wacc)
    graph.add_node("equity_value", calculate_pv)

    return graph
