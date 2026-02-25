from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class BenchmarkResult:
    model: str
    iterations: int
    p50_reference_ms: float
    p50_optimized_ms: float
    speedup_ratio: float
    improvement_pct: float
    max_abs_diff: float
    mean_abs_error: float


def _saas_reference(
    *,
    growth_shock: np.ndarray,
    margin_shock: np.ndarray,
    wacc: np.ndarray,
    terminal_growth: np.ndarray,
) -> np.ndarray:
    base_growth = np.array([0.15, 0.14, 0.12, 0.10, 0.08], dtype=float)
    base_margin = np.array([0.10, 0.12, 0.14, 0.16, 0.18], dtype=float)
    da_rates = np.array([0.03, 0.03, 0.03, 0.03, 0.03], dtype=float)
    capex_rates = np.array([0.05, 0.05, 0.05, 0.05, 0.05], dtype=float)
    wc_rates = np.array([0.01, 0.01, 0.01, 0.01, 0.01], dtype=float)
    sbc_rates = np.array([0.02, 0.02, 0.02, 0.02, 0.02], dtype=float)
    initial_revenue = 100.0
    tax_rate = 0.21
    cash = 10.0
    total_debt = 5.0
    preferred_stock = 0.0
    shares_outstanding = 100.0

    years = base_growth.shape[0]
    batch_size = growth_shock.shape[0]
    growth_rates = np.clip(
        base_growth[np.newaxis, :] + growth_shock[:, np.newaxis], -0.80, 1.50
    )
    operating_margins = np.clip(
        base_margin[np.newaxis, :] + margin_shock[:, np.newaxis], -0.50, 0.70
    )

    projected_revenue = np.empty((batch_size, years), dtype=float)
    revenue_level = np.full(batch_size, initial_revenue, dtype=float)
    for year_idx in range(years):
        revenue_level = revenue_level * (1.0 + growth_rates[:, year_idx])
        projected_revenue[:, year_idx] = revenue_level

    ebit = projected_revenue * operating_margins
    nopat = ebit * (1.0 - tax_rate)
    da = projected_revenue * da_rates[np.newaxis, :]
    capex = projected_revenue * capex_rates[np.newaxis, :]
    sbc = projected_revenue * sbc_rates[np.newaxis, :]
    previous_revenue = np.concatenate(
        [
            np.full((batch_size, 1), initial_revenue, dtype=float),
            projected_revenue[:, :-1],
        ],
        axis=1,
    )
    delta_wc = (projected_revenue - previous_revenue) * wc_rates[np.newaxis, :]
    fcff = nopat + da - capex - delta_wc + sbc

    discount_years = np.arange(1, years + 1, dtype=float)
    terminal = np.minimum(terminal_growth, wacc - 0.001)
    discount_curve = np.power(1.0 + wacc[:, np.newaxis], discount_years[np.newaxis, :])
    pv_fcff = np.sum(fcff / discount_curve, axis=1)
    final_fcff = fcff[:, -1]
    terminal_value = final_fcff * (1.0 + terminal) / (wacc - terminal)
    pv_terminal = terminal_value / np.power(1.0 + wacc, years)
    enterprise_value = pv_fcff + pv_terminal
    equity_value = enterprise_value + cash - total_debt - preferred_stock
    return equity_value / shares_outstanding


def _saas_optimized(
    *,
    growth_shock: np.ndarray,
    margin_shock: np.ndarray,
    wacc: np.ndarray,
    terminal_growth: np.ndarray,
) -> np.ndarray:
    base_growth = np.array([0.15, 0.14, 0.12, 0.10, 0.08], dtype=float)
    base_margin = np.array([0.10, 0.12, 0.14, 0.16, 0.18], dtype=float)
    da_rates = np.array([0.03, 0.03, 0.03, 0.03, 0.03], dtype=float)
    capex_rates = np.array([0.05, 0.05, 0.05, 0.05, 0.05], dtype=float)
    wc_rates = np.array([0.01, 0.01, 0.01, 0.01, 0.01], dtype=float)
    sbc_rates = np.array([0.02, 0.02, 0.02, 0.02, 0.02], dtype=float)
    initial_revenue = 100.0
    tax_rate = 0.21
    cash = 10.0
    total_debt = 5.0
    preferred_stock = 0.0
    shares_outstanding = 100.0

    years = base_growth.shape[0]
    batch_size = growth_shock.shape[0]
    discount_years = np.arange(1, years + 1, dtype=float)
    growth_rates = np.clip(
        base_growth[np.newaxis, :] + growth_shock[:, np.newaxis], -0.80, 1.50
    )
    operating_margins = np.clip(
        base_margin[np.newaxis, :] + margin_shock[:, np.newaxis], -0.50, 0.70
    )

    projected_revenue = np.empty((batch_size, years), dtype=float)
    revenue_level = np.full(batch_size, initial_revenue, dtype=float)
    for year_idx in range(years):
        revenue_level *= 1.0 + growth_rates[:, year_idx]
        projected_revenue[:, year_idx] = revenue_level
    ebit = projected_revenue * operating_margins
    nopat = ebit * (1.0 - tax_rate)
    da = projected_revenue * da_rates[np.newaxis, :]
    capex = projected_revenue * capex_rates[np.newaxis, :]
    sbc = projected_revenue * sbc_rates[np.newaxis, :]
    previous_revenue = np.empty_like(projected_revenue)
    previous_revenue[:, 0] = initial_revenue
    previous_revenue[:, 1:] = projected_revenue[:, :-1]
    delta_wc = (projected_revenue - previous_revenue) * wc_rates[np.newaxis, :]
    fcff = nopat + da - capex - delta_wc + sbc

    terminal = np.minimum(terminal_growth, wacc - 0.001)
    discount_curve = np.power(1.0 + wacc[:, np.newaxis], discount_years[np.newaxis, :])
    pv_fcff = np.sum(fcff / discount_curve, axis=1)
    final_fcff = fcff[:, -1]
    terminal_value = final_fcff * (1.0 + terminal) / (wacc - terminal)
    pv_terminal = terminal_value / np.power(1.0 + wacc, years)
    enterprise_value = pv_fcff + pv_terminal
    equity_value = enterprise_value + cash - total_debt - preferred_stock
    return equity_value / shares_outstanding


def _bank_reference(
    *,
    provision_rate: np.ndarray,
    income_growth_shock: np.ndarray,
    risk_free_rate: np.ndarray,
    terminal_growth: np.ndarray,
) -> np.ndarray:
    base_growth = np.array([0.06, 0.055, 0.05, 0.045, 0.04], dtype=float)
    initial_net_income = 35.0
    rwa_intensity = 0.025
    tier1_target_ratio = 0.11
    initial_capital = 280.0
    beta = 1.2
    market_risk_premium = 0.05
    shares_outstanding = 3000.0

    years = base_growth.shape[0]
    batch_size = provision_rate.shape[0]
    adjusted_initial_income = initial_net_income * (1.0 - provision_rate)
    growth_rates = np.clip(
        base_growth[np.newaxis, :] + income_growth_shock[:, np.newaxis], -0.80, 1.50
    )
    net_income = np.empty((batch_size, years), dtype=float)
    income_level = adjusted_initial_income.copy()
    for year_idx in range(years):
        income_level = income_level * (1.0 + growth_rates[:, year_idx])
        net_income[:, year_idx] = income_level

    rwa = net_income / rwa_intensity
    required_capital = rwa * tier1_target_ratio
    previous_capital = np.concatenate(
        [
            np.full((batch_size, 1), initial_capital, dtype=float),
            required_capital[:, :-1],
        ],
        axis=1,
    )
    dividends = net_income - (required_capital - previous_capital)
    cost_of_equity = risk_free_rate + (beta * market_risk_premium)
    terminal = np.minimum(terminal_growth, cost_of_equity - 0.001)

    discount_years = np.arange(1, years + 1, dtype=float)
    discount_curve = np.power(
        1.0 + cost_of_equity[:, np.newaxis], discount_years[np.newaxis, :]
    )
    pv_dividends = np.sum(dividends / discount_curve, axis=1)
    last_dividend = dividends[:, -1]
    terminal_value = last_dividend * (1.0 + terminal) / (cost_of_equity - terminal)
    pv_terminal = terminal_value / np.power(1.0 + cost_of_equity, years)
    equity_value = pv_dividends + pv_terminal
    return equity_value / shares_outstanding


def _bank_optimized(
    *,
    provision_rate: np.ndarray,
    income_growth_shock: np.ndarray,
    risk_free_rate: np.ndarray,
    terminal_growth: np.ndarray,
) -> np.ndarray:
    base_growth = np.array([0.06, 0.055, 0.05, 0.045, 0.04], dtype=float)
    initial_net_income = 35.0
    rwa_intensity = 0.025
    tier1_target_ratio = 0.11
    initial_capital = 280.0
    beta = 1.2
    market_risk_premium = 0.05
    shares_outstanding = 3000.0

    years = base_growth.shape[0]
    batch_size = provision_rate.shape[0]
    discount_years = np.arange(1, years + 1, dtype=float)
    adjusted_initial_income = initial_net_income * (1.0 - provision_rate)
    growth_rates = np.clip(
        base_growth[np.newaxis, :] + income_growth_shock[:, np.newaxis], -0.80, 1.50
    )
    net_income = np.empty((batch_size, years), dtype=float)
    income_level = adjusted_initial_income.copy()
    for year_idx in range(years):
        income_level *= 1.0 + growth_rates[:, year_idx]
        net_income[:, year_idx] = income_level

    rwa = net_income / rwa_intensity
    required_capital = rwa * tier1_target_ratio
    previous_capital = np.empty_like(required_capital)
    previous_capital[:, 0] = initial_capital
    previous_capital[:, 1:] = required_capital[:, :-1]
    dividends = net_income - (required_capital - previous_capital)
    cost_of_equity = risk_free_rate + (beta * market_risk_premium)
    terminal = np.minimum(terminal_growth, cost_of_equity - 0.001)

    discount_curve = np.power(
        1.0 + cost_of_equity[:, np.newaxis], discount_years[np.newaxis, :]
    )
    pv_dividends = np.sum(dividends / discount_curve, axis=1)
    last_dividend = dividends[:, -1]
    terminal_value = last_dividend * (1.0 + terminal) / (cost_of_equity - terminal)
    pv_terminal = terminal_value / np.power(1.0 + cost_of_equity, years)
    equity_value = pv_dividends + pv_terminal
    return equity_value / shares_outstanding


def _reit_reference(*, occupancy_rate: np.ndarray, cap_rate: np.ndarray) -> np.ndarray:
    base_ffo = 120.0
    depreciation_and_amortization = 50.0
    maintenance_capex_ratio = 0.8
    cash = 100.0
    total_debt = 300.0
    preferred_stock = 0.0
    shares_outstanding = 1000.0

    adjusted_cap_rate = np.maximum(cap_rate, 1e-6)
    ffo = base_ffo * occupancy_rate
    maintenance_capex = depreciation_and_amortization * maintenance_capex_ratio
    affo = ffo - maintenance_capex
    enterprise_value = affo / adjusted_cap_rate
    equity_value = enterprise_value + cash - total_debt - preferred_stock
    return equity_value / shares_outstanding


def _reit_optimized(*, occupancy_rate: np.ndarray, cap_rate: np.ndarray) -> np.ndarray:
    base_ffo = 120.0
    depreciation_and_amortization = 50.0
    maintenance_capex_ratio = 0.8
    cash = 100.0
    total_debt = 300.0
    preferred_stock = 0.0
    shares_outstanding = 1000.0

    adjusted_cap_rate = np.maximum(cap_rate, 1e-6)
    ffo = base_ffo * occupancy_rate
    maintenance_capex = depreciation_and_amortization * maintenance_capex_ratio
    affo = ffo - maintenance_capex
    enterprise_value = affo / adjusted_cap_rate
    equity_value = enterprise_value + cash - total_debt - preferred_stock
    return equity_value / shares_outstanding


def _measure_ms(func, *, repeats: int, inner_loops: int) -> list[float]:
    timings: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        for _ in range(inner_loops):
            func()
        end = time.perf_counter()
        timings.append(((end - start) * 1000.0) / inner_loops)
    return timings


def _benchmark_case(
    *,
    model: str,
    iterations: int,
    repeats: int,
    reference_fn,
    optimized_fn,
    sampled_kwargs: dict[str, np.ndarray],
    inner_loops: int,
) -> BenchmarkResult:
    ref_times = _measure_ms(
        lambda: reference_fn(**sampled_kwargs),
        repeats=repeats,
        inner_loops=inner_loops,
    )
    opt_times = _measure_ms(
        lambda: optimized_fn(**sampled_kwargs),
        repeats=repeats,
        inner_loops=inner_loops,
    )
    ref_values = reference_fn(**sampled_kwargs)
    opt_values = optimized_fn(**sampled_kwargs)

    abs_diff = np.abs(ref_values - opt_values)
    p50_ref = statistics.median(ref_times)
    p50_opt = statistics.median(opt_times)
    speedup = (p50_ref / p50_opt) if p50_opt > 0 else 0.0
    improvement = ((p50_ref - p50_opt) / p50_ref * 100.0) if p50_ref > 0 else 0.0

    return BenchmarkResult(
        model=model,
        iterations=iterations,
        p50_reference_ms=round(p50_ref, 4),
        p50_optimized_ms=round(p50_opt, 4),
        speedup_ratio=round(speedup, 4),
        improvement_pct=round(improvement, 2),
        max_abs_diff=float(np.max(abs_diff)),
        mean_abs_error=float(np.mean(abs_diff)),
    )


def _render_markdown(results: list[BenchmarkResult], tolerance: float) -> str:
    now = datetime.now(UTC).isoformat()
    lines = [
        "# Fundamental MC Batch Kernel Profiling",
        "",
        f"- generated_at: `{now}`",
        f"- tolerance: `{tolerance}`",
        "",
        "| Model | Iterations | Ref p50 (ms) | Opt p50 (ms) | Speedup | Improvement | Max Abs Diff | MAE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in results:
        lines.append(
            f"| {item.model} | {item.iterations} | {item.p50_reference_ms:.4f} | "
            f"{item.p50_optimized_ms:.4f} | {item.speedup_ratio:.4f}x | "
            f"{item.improvement_pct:.2f}% | {item.max_abs_diff:.6g} | {item.mean_abs_error:.6g} |"
        )
    lines.append("")
    lines.append("## Gate")
    lines.append("")
    gate_failures: list[str] = []
    for item in results:
        if item.max_abs_diff > tolerance:
            gate_failures.append(
                f"- FAIL `{item.model}@{item.iterations}` max_abs_diff={item.max_abs_diff:.6g}"
            )
    if gate_failures:
        lines.extend(gate_failures)
    else:
        lines.append("- PASS numerical consistency within tolerance.")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Profile fundamental MC batch kernels (reference vs optimized)."
    )
    parser.add_argument(
        "--iterations",
        nargs="+",
        type=int,
        default=[1000, 10000],
        help="Iteration counts to benchmark.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=9,
        help="Repetitions per benchmark sample; p50 is reported.",
    )
    parser.add_argument(
        "--inner-loops",
        type=int,
        default=0,
        help="If >0, run each timed sample for N inner loops (stabilizes micro-benchmarks).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for synthetic sampled inputs.",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1e-9,
        help="Max absolute error tolerance gate.",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=PROJECT_ROOT / "reports" / "fundamental_mc_kernel_profile.json",
    )
    parser.add_argument(
        "--report-md",
        type=Path,
        default=PROJECT_ROOT / "reports" / "fundamental_mc_kernel_profile.md",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rng = np.random.default_rng(args.seed)
    results: list[BenchmarkResult] = []

    for iterations in args.iterations:
        inner_loops = args.inner_loops
        if inner_loops <= 0:
            inner_loops = 20 if iterations <= 1000 else 8
        # SaaS
        saas_kwargs = {
            "growth_shock": rng.normal(0.0, 0.03, size=iterations),
            "margin_shock": rng.normal(0.0, 0.02, size=iterations),
            "wacc": np.clip(rng.normal(0.10, 0.015, size=iterations), 0.03, 0.30),
            "terminal_growth": np.clip(
                rng.normal(0.025, 0.005, size=iterations), -0.01, 0.05
            ),
        }
        results.append(
            _benchmark_case(
                model="saas",
                iterations=iterations,
                repeats=args.repeats,
                reference_fn=_saas_reference,
                optimized_fn=_saas_optimized,
                sampled_kwargs=saas_kwargs,
                inner_loops=inner_loops,
            )
        )

        # Bank
        bank_kwargs = {
            "provision_rate": np.clip(
                rng.normal(0.012, 0.004, size=iterations), 0.0, 0.30
            ),
            "income_growth_shock": rng.normal(0.0, 0.03, size=iterations),
            "risk_free_rate": np.clip(
                rng.normal(0.042, 0.01, size=iterations), 0.0, 0.20
            ),
            "terminal_growth": np.clip(
                rng.normal(0.02, 0.005, size=iterations), -0.01, 0.06
            ),
        }
        results.append(
            _benchmark_case(
                model="bank",
                iterations=iterations,
                repeats=args.repeats,
                reference_fn=_bank_reference,
                optimized_fn=_bank_optimized,
                sampled_kwargs=bank_kwargs,
                inner_loops=inner_loops,
            )
        )

        # REIT
        reit_kwargs = {
            "occupancy_rate": np.clip(
                rng.triangular(0.70, 0.90, 0.98, size=iterations), 0.50, 1.0
            ),
            "cap_rate": np.clip(rng.normal(0.08, 0.015, size=iterations), 0.02, 0.25),
        }
        results.append(
            _benchmark_case(
                model="reit",
                iterations=iterations,
                repeats=args.repeats,
                reference_fn=_reit_reference,
                optimized_fn=_reit_optimized,
                sampled_kwargs=reit_kwargs,
                inner_loops=inner_loops,
            )
        )

    gate_passed = all(item.max_abs_diff <= args.tolerance for item in results)
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "iterations": args.iterations,
        "repeats": args.repeats,
        "seed": args.seed,
        "tolerance": args.tolerance,
        "gate_passed": gate_passed,
    }
    payload = {
        "summary": summary,
        "results": [
            {
                "model": item.model,
                "iterations": item.iterations,
                "p50_reference_ms": item.p50_reference_ms,
                "p50_optimized_ms": item.p50_optimized_ms,
                "speedup_ratio": item.speedup_ratio,
                "improvement_pct": item.improvement_pct,
                "max_abs_diff": item.max_abs_diff,
                "mean_abs_error": item.mean_abs_error,
            }
            for item in results
        ],
    }

    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.report_md.parent.mkdir(parents=True, exist_ok=True)
    args.report_md.write_text(
        _render_markdown(results, args.tolerance), encoding="utf-8"
    )

    print(f"[mc-kernel-profile] json={args.report_json}")
    print(f"[mc-kernel-profile] markdown={args.report_md}")
    print(f"[mc-kernel-profile] gate_passed={gate_passed}")
    return 0 if gate_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
