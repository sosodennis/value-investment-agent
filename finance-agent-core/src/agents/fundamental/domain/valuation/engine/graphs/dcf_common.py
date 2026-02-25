from __future__ import annotations


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def projection_years(growth_rates: list[float]) -> int:
    if not growth_rates:
        raise ValueError("growth_rates cannot be empty")
    return len(growth_rates)


def converge_series(
    values: list[float],
    *,
    target: float,
    start_index: int,
    min_value: float,
    max_value: float,
) -> list[float]:
    if not values:
        raise ValueError("projection series cannot be empty")

    clamped_target = clamp(target, min_value, max_value)
    clamped = [clamp(float(value), min_value, max_value) for value in values]
    n = len(clamped)
    start = max(0, min(start_index, n - 1))
    if start >= n - 1:
        clamped[-1] = clamped_target
        return clamped

    start_value = clamped[start]
    steps = n - start - 1
    for idx in range(start + 1, n):
        progress = (idx - start) / steps
        clamped[idx] = start_value + ((clamped_target - start_value) * progress)
    clamped[-1] = clamped_target
    return clamped


def _assert_same_length(name: str, left: list[float], right: list[float]) -> None:
    if len(left) != len(right):
        raise ValueError(f"{name} series length mismatch: {len(left)} vs {len(right)}")


def project_revenue(
    initial_revenue: float, growth_rates_converged: list[float]
) -> list[float]:
    if initial_revenue <= 0:
        raise ValueError("initial_revenue must be positive")
    if not growth_rates_converged:
        raise ValueError("growth_rates_converged cannot be empty")

    projected: list[float] = []
    current = initial_revenue
    for growth in growth_rates_converged:
        current = current * (1.0 + growth)
        projected.append(current)
    return projected


def calculate_ebit(
    projected_revenue: list[float], operating_margins_converged: list[float]
) -> list[float]:
    _assert_same_length(
        "projected_revenue/operating_margins_converged",
        projected_revenue,
        operating_margins_converged,
    )
    return [
        revenue * margin
        for revenue, margin in zip(
            projected_revenue, operating_margins_converged, strict=False
        )
    ]


def calculate_nopat(ebit: list[float], tax_rate: float) -> list[float]:
    effective_tax = clamp(tax_rate, 0.0, 0.60)
    return [value * (1.0 - effective_tax) for value in ebit]


def calculate_delta_wc(
    projected_revenue: list[float],
    initial_revenue: float,
    wc_rates_converged: list[float],
) -> list[float]:
    _assert_same_length(
        "projected_revenue/wc_rates_converged",
        projected_revenue,
        wc_rates_converged,
    )
    deltas: list[float] = []
    previous = initial_revenue
    for revenue, wc_rate in zip(projected_revenue, wc_rates_converged, strict=False):
        delta_revenue = revenue - previous
        deltas.append(delta_revenue * wc_rate)
        previous = revenue
    return deltas


def calculate_fcff(
    nopat: list[float],
    projected_revenue: list[float],
    da_rates_converged: list[float],
    capex_rates_converged: list[float],
    delta_wc: list[float],
    sbc_rates_converged: list[float],
) -> list[float]:
    _assert_same_length("nopat/projected_revenue", nopat, projected_revenue)
    _assert_same_length(
        "projected_revenue/da_rates_converged", projected_revenue, da_rates_converged
    )
    _assert_same_length(
        "projected_revenue/capex_rates_converged",
        projected_revenue,
        capex_rates_converged,
    )
    _assert_same_length("projected_revenue/delta_wc", projected_revenue, delta_wc)
    _assert_same_length(
        "projected_revenue/sbc_rates_converged", projected_revenue, sbc_rates_converged
    )
    fcff: list[float] = []
    for index, revenue in enumerate(projected_revenue):
        da = revenue * da_rates_converged[index]
        capex = revenue * capex_rates_converged[index]
        sbc = revenue * sbc_rates_converged[index]
        fcff.append(nopat[index] + da - capex - delta_wc[index] + sbc)
    return fcff


def calculate_reinvestment_rates(
    projected_revenue: list[float],
    da_rates_converged: list[float],
    capex_rates_converged: list[float],
    delta_wc: list[float],
) -> list[float]:
    _assert_same_length(
        "projected_revenue/da_rates_converged", projected_revenue, da_rates_converged
    )
    _assert_same_length(
        "projected_revenue/capex_rates_converged",
        projected_revenue,
        capex_rates_converged,
    )
    _assert_same_length("projected_revenue/delta_wc", projected_revenue, delta_wc)
    output: list[float] = []
    for index, revenue in enumerate(projected_revenue):
        if revenue == 0:
            output.append(0.0)
            continue
        reinvestment = (
            (revenue * capex_rates_converged[index])
            - (revenue * da_rates_converged[index])
            + delta_wc[index]
        )
        output.append(reinvestment / revenue)
    return output


def final_fcff(fcff: list[float]) -> float:
    if not fcff:
        raise ValueError("fcff cannot be empty")
    return fcff[-1]


def effective_terminal_growth(terminal_growth: float, wacc: float) -> float:
    bounded = clamp(terminal_growth, -0.01, 0.05)
    ceiling = wacc - 0.005
    if ceiling <= -0.01:
        raise ValueError(
            "wacc must be greater than 0.5% for terminal value calculation"
        )
    return min(bounded, ceiling)


def calculate_terminal_value(
    final_fcff: float, wacc: float, terminal_growth_effective: float
) -> float:
    if terminal_growth_effective >= wacc:
        raise ValueError("terminal_growth_effective must be less than wacc")
    denominator = wacc - terminal_growth_effective
    if denominator <= 1e-6:
        raise ValueError("terminal value denominator too small")
    return (final_fcff * (1.0 + terminal_growth_effective)) / denominator


def calculate_pv_fcff(fcff: list[float], wacc: float) -> float:
    pv = 0.0
    for period, cash_flow in enumerate(fcff, start=1):
        pv += cash_flow / ((1.0 + wacc) ** period)
    return pv


def calculate_pv_terminal(
    terminal_value: float, wacc: float, projection_years: int
) -> float:
    return terminal_value / ((1.0 + wacc) ** projection_years)


def calculate_enterprise_value(pv_fcff: float, pv_terminal: float) -> float:
    return pv_fcff + pv_terminal


def calculate_equity_value(
    enterprise_value: float, cash: float, total_debt: float, preferred_stock: float
) -> float:
    return enterprise_value + cash - total_debt - preferred_stock


def calculate_intrinsic_value(equity_value: float, shares_outstanding: float) -> float:
    if shares_outstanding <= 0:
        raise ValueError("shares_outstanding must be positive")
    return equity_value / shares_outstanding
