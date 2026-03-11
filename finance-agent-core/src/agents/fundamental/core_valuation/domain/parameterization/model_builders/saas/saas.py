from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.agents.fundamental.shared.contracts.traceable import (
    ManualProvenance,
    TraceableField,
)

from ....policies.manual_assumption_policy import (
    DEFAULT_DA_RATE,
    DEFAULT_TERMINAL_GROWTH,
    assume_rate,
)
from ....report_contract import FinancialReport, IndustrialExtension
from ...core_ops_service import ratio_with_optional_inputs
from ...types import MonteCarloControls, TraceInput
from ..shared.capital_structure_value_extraction_service import (
    extract_filing_capital_structure_market_values,
)
from ..shared.capm_market_defaults_service import resolve_capm_market_defaults
from ..shared.common_output_assembly_service import (
    build_base_params,
    build_capital_structure_params,
    build_capital_structure_trace_inputs,
    build_capm_market_params,
    build_capm_market_trace_inputs,
    build_monte_carlo_params,
)
from ..shared.missing_metrics_service import (
    apply_missing_metric_policy,
    collect_missing_metric_names,
)

DEFAULT_SAAS_RISK_FREE_RATE = 0.042
DEFAULT_SAAS_TAX_RATE = 0.21
DEFAULT_SAAS_CAPEX_RATE = 0.04
DEFAULT_SAAS_SBC_RATE = 0.00
DEFAULT_SAAS_WC_RATE = 0.00
DEFAULT_SAAS_BETA = 1.0
BETA_FLOOR = 0.50
BETA_CEILING = 1.80
WACC_FLOOR = 0.05
WACC_CEILING = 0.30
TERMINAL_GROWTH_FLOOR = -0.02
TERMINAL_GROWTH_CEILING = 0.04
TERMINAL_GROWTH_SPREAD_BUFFER = 0.005
S3_LITE_DILUTION_PROXY_CEILING = 0.20
TERMINAL_GROWTH_STALE_FALLBACK_MODE_ENV = (
    "FUNDAMENTAL_TERMINAL_GROWTH_STALE_FALLBACK_MODE"
)
TERMINAL_GROWTH_STALE_FALLBACK_DEFAULT = "default_only"
TERMINAL_GROWTH_STALE_FALLBACK_FILING_FIRST = "filing_first_then_default"
LONG_RUN_GROWTH_NOMINAL_BRIDGE_INFLATION_ENV = (
    "FUNDAMENTAL_LONG_RUN_GROWTH_NOMINAL_BRIDGE_INFLATION"
)
LONG_RUN_GROWTH_NOMINAL_BRIDGE_INFLATION_DEFAULT = 0.02
LONG_RUN_GROWTH_REAL_SERIES_TOKEN = "a191rl1q225sbea"
SHARES_SCOPE_MISMATCH_RATIO_THRESHOLD = 0.20
BETA_MEAN_REVERSION_RAW_WEIGHT = 0.67
BETA_MEAN_REVERSION_ANCHOR_WEIGHT = 0.33
BETA_MEAN_REVERSION_ANCHOR = 1.0
BETA_MEAN_REVERSION_MIN_RAW_BETA = 1.0
BETA_MEAN_REVERSION_MAX_RAW_BETA = 1.5
BETA_MEAN_REVERSION_DEGRADED_PREMIUM_TRIGGER = 0.30
_SAAS_WARN_ONLY_MISSING_METRICS = (
    "tax_rate",
    "da_rates",
    "capex_rates",
    "wc_rates",
    "sbc_rates",
)


@dataclass(frozen=True)
class _TerminalGrowthPathDiagnostics:
    fallback_mode: str
    anchor_source: str
    market_anchor_value: float | None
    market_anchor_raw_value: float | None
    market_anchor_basis: str
    market_anchor_source_detail: str | None
    nominal_bridge_inflation: float | None
    filing_anchor_value: float | None
    market_anchor_is_stale: bool | None
    market_anchor_staleness_days: int | None
    market_anchor_stale_max_days: int | None

    def to_metadata(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "terminal_growth_fallback_mode": self.fallback_mode,
            "terminal_growth_anchor_source": self.anchor_source,
            "long_run_growth_anchor_market_basis": self.market_anchor_basis,
        }
        if self.market_anchor_value is not None:
            payload["long_run_growth_anchor_market"] = self.market_anchor_value
        if self.market_anchor_raw_value is not None:
            payload["long_run_growth_anchor_market_raw"] = self.market_anchor_raw_value
        if isinstance(self.market_anchor_source_detail, str):
            payload["long_run_growth_anchor_source_detail"] = (
                self.market_anchor_source_detail
            )
        if self.nominal_bridge_inflation is not None:
            payload["long_run_growth_nominal_bridge_inflation"] = (
                self.nominal_bridge_inflation
            )
        if self.filing_anchor_value is not None:
            payload["long_run_growth_anchor_filing"] = self.filing_anchor_value

        staleness: dict[str, object] = {}
        if isinstance(self.market_anchor_is_stale, bool):
            staleness["is_stale"] = self.market_anchor_is_stale
        if isinstance(self.market_anchor_staleness_days, int):
            staleness["days"] = self.market_anchor_staleness_days
        if isinstance(self.market_anchor_stale_max_days, int):
            staleness["max_days"] = self.market_anchor_stale_max_days
        if staleness:
            payload["long_run_growth_anchor_staleness"] = staleness
        return payload


@dataclass(frozen=True)
class _SharesPathDiagnostics:
    selected_source: str
    shares_scope: str
    equity_value_scope: str
    scope_mismatch_detected: bool
    filing_shares: float | None
    market_shares: float | None
    selected_shares: float | None
    scope_mismatch_ratio: float | None

    def to_metadata(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "selected_source": self.selected_source,
            "shares_scope": self.shares_scope,
            "equity_value_scope": self.equity_value_scope,
            "scope_mismatch_detected": self.scope_mismatch_detected,
        }
        if self.filing_shares is not None:
            payload["filing_shares"] = self.filing_shares
        if self.market_shares is not None:
            payload["market_shares"] = self.market_shares
        if self.selected_shares is not None:
            payload["selected_shares"] = self.selected_shares
        if self.scope_mismatch_ratio is not None:
            payload["scope_mismatch_ratio"] = self.scope_mismatch_ratio
        return payload


@dataclass(frozen=True)
class _SaasCapmTerminalInputs:
    risk_free_rate: float
    beta: float
    market_risk_premium: float
    wacc_tf: TraceableField[float]
    terminal_growth_tf: TraceableField[float]
    terminal_growth_path: _TerminalGrowthPathDiagnostics


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _to_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return float(normalized)
        except ValueError:
            return None
    return None


def _to_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return int(float(normalized))
        except ValueError:
            return None
    return None


def _resolve_target_premium(
    market_snapshot: Mapping[str, object] | None,
) -> float | None:
    if not isinstance(market_snapshot, Mapping):
        return None
    current_price = _to_float(market_snapshot.get("current_price"))
    target_mean_price = _to_float(market_snapshot.get("target_mean_price"))
    if (
        current_price is None
        or current_price <= 0
        or target_mean_price is None
        or target_mean_price <= 0
    ):
        return None
    return (target_mean_price / current_price) - 1.0


def _resolve_beta_mean_reversion(
    *,
    raw_beta: float,
    market_snapshot: Mapping[str, object] | None,
    filing_shares: float | None,
) -> tuple[float, str | None]:
    if (
        raw_beta <= BETA_MEAN_REVERSION_MIN_RAW_BETA
        or raw_beta > BETA_MEAN_REVERSION_MAX_RAW_BETA
    ):
        return raw_beta, None

    premium = _resolve_target_premium(market_snapshot)
    if premium is None or premium <= 0:
        return raw_beta, None

    fallback_reason: str | None = None
    market_shares: float | None = None
    if isinstance(market_snapshot, Mapping):
        fallback_reason_raw = market_snapshot.get("target_consensus_fallback_reason")
        if isinstance(fallback_reason_raw, str) and fallback_reason_raw.strip():
            fallback_reason = fallback_reason_raw.strip()
        market_shares = _to_float(market_snapshot.get("shares_outstanding"))

    if (
        filing_shares is not None
        and filing_shares > 0
        and market_shares is not None
        and market_shares > 0
    ):
        mismatch_ratio = abs(filing_shares - market_shares) / filing_shares
        if mismatch_ratio >= SHARES_SCOPE_MISMATCH_RATIO_THRESHOLD:
            return (
                raw_beta,
                "beta mean-reversion skipped "
                f"(shares_scope_mismatch_ratio={mismatch_ratio:.2%})",
            )

    if (
        fallback_reason is not None
        and premium < BETA_MEAN_REVERSION_DEGRADED_PREMIUM_TRIGGER
    ):
        return (
            raw_beta,
            "beta mean-reversion skipped "
            f"(degraded_low_premium_consensus premium={premium:.2%}, "
            f"fallback_reason={fallback_reason})",
        )

    adjusted_beta = (raw_beta * BETA_MEAN_REVERSION_RAW_WEIGHT) + (
        BETA_MEAN_REVERSION_ANCHOR * BETA_MEAN_REVERSION_ANCHOR_WEIGHT
    )
    if adjusted_beta >= raw_beta:
        return raw_beta, None
    return (
        adjusted_beta,
        "beta mean-reversion applied "
        f"(method=blume_67_33, raw_beta={raw_beta:.3f}, "
        f"adjusted_beta={adjusted_beta:.3f}, premium={premium:.2%}, "
        f"fallback_reason={fallback_reason or 'none'})",
    )


def _extract_market_datum_staleness(
    market_snapshot: Mapping[str, object] | None,
    *,
    field: str,
) -> tuple[bool | None, int | None, int | None]:
    if market_snapshot is None:
        return None, None, None
    market_datums_raw = market_snapshot.get("market_datums")
    if not isinstance(market_datums_raw, Mapping):
        return None, None, None
    datum_raw = market_datums_raw.get(field)
    if not isinstance(datum_raw, Mapping):
        return None, None, None
    staleness_raw = datum_raw.get("staleness")
    if not isinstance(staleness_raw, Mapping):
        return None, None, None
    is_stale_raw = staleness_raw.get("is_stale")
    days_raw = staleness_raw.get("days")
    max_days_raw = staleness_raw.get("max_days")
    is_stale = is_stale_raw if isinstance(is_stale_raw, bool) else None
    stale_days = days_raw if isinstance(days_raw, int) else _to_int(days_raw)
    stale_max_days = (
        max_days_raw if isinstance(max_days_raw, int) else _to_int(max_days_raw)
    )
    return is_stale, stale_days, stale_max_days


def _extract_market_datum_source_detail(
    market_snapshot: Mapping[str, object] | None,
    *,
    field: str,
) -> str | None:
    if market_snapshot is None:
        return None
    market_datums_raw = market_snapshot.get("market_datums")
    if not isinstance(market_datums_raw, Mapping):
        return None
    datum_raw = market_datums_raw.get(field)
    if not isinstance(datum_raw, Mapping):
        return None
    source_detail_raw = datum_raw.get("source_detail")
    if isinstance(source_detail_raw, str):
        source_detail = source_detail_raw.strip()
        if source_detail:
            return source_detail
    return None


def _resolve_nominal_growth_bridge_inflation() -> float:
    raw = os.getenv(LONG_RUN_GROWTH_NOMINAL_BRIDGE_INFLATION_ENV)
    if raw is None:
        return LONG_RUN_GROWTH_NOMINAL_BRIDGE_INFLATION_DEFAULT
    parsed = _to_float(raw)
    if parsed is None:
        return LONG_RUN_GROWTH_NOMINAL_BRIDGE_INFLATION_DEFAULT
    if parsed > 1.0:
        parsed /= 100.0
    return _clamp(parsed, -0.01, 0.08)


def _resolve_market_long_run_growth_anchor_nominal(
    *,
    market_anchor_raw: float | None,
    market_anchor_source_detail: str | None,
    assumptions: list[str],
) -> tuple[float | None, str, float | None]:
    if market_anchor_raw is None:
        return None, "unknown", None
    if not isinstance(market_anchor_source_detail, str):
        return market_anchor_raw, "nominal_or_unknown", None
    normalized_detail = market_anchor_source_detail.strip().lower()
    if LONG_RUN_GROWTH_REAL_SERIES_TOKEN not in normalized_detail:
        return market_anchor_raw, "nominal_or_unknown", None

    inflation_bridge = _resolve_nominal_growth_bridge_inflation()
    nominal_anchor = (1.0 + market_anchor_raw) * (1.0 + inflation_bridge) - 1.0
    assumptions.append(
        "terminal_growth market anchor converted from real to nominal "
        f"(real={market_anchor_raw:.2%}, inflation_bridge={inflation_bridge:.2%}, "
        f"nominal={nominal_anchor:.2%}, source_detail={market_anchor_source_detail})"
    )
    return nominal_anchor, "real_to_nominal_bridge", inflation_bridge


def _derive_filing_terminal_growth_anchor(
    reports: list[FinancialReport],
) -> float | None:
    points: list[tuple[int, float]] = []
    for report in reports:
        year = _to_int(report.base.fiscal_year.value)
        revenue = _to_float(report.base.total_revenue.value)
        if year is None or revenue is None or revenue <= 0:
            continue
        points.append((year, revenue))

    if len(points) < 2:
        return None
    points.sort(key=lambda item: item[0])
    first_year, first_revenue = points[0]
    last_year, last_revenue = points[-1]
    if last_revenue <= 0 or first_revenue <= 0:
        return None

    span_years = last_year - first_year
    if span_years > 0:
        return (last_revenue / first_revenue) ** (1.0 / float(span_years)) - 1.0

    previous_revenue = points[-2][1]
    if previous_revenue <= 0:
        return None
    return (last_revenue - previous_revenue) / previous_revenue


def _resolve_terminal_growth_stale_fallback_mode() -> str:
    raw = os.getenv(TERMINAL_GROWTH_STALE_FALLBACK_MODE_ENV)
    if raw is None:
        return TERMINAL_GROWTH_STALE_FALLBACK_DEFAULT
    token = raw.strip().lower()
    if token in {
        TERMINAL_GROWTH_STALE_FALLBACK_DEFAULT,
        TERMINAL_GROWTH_STALE_FALLBACK_FILING_FIRST,
    }:
        return token
    return TERMINAL_GROWTH_STALE_FALLBACK_DEFAULT


def _resolve_interest_cost_rate(
    *,
    report: FinancialReport,
    total_debt: float | None,
    assumptions: list[str],
) -> float | None:
    direct_rate = _to_float(report.base.interest_cost_rate.value)
    if direct_rate is not None and direct_rate > 0:
        return direct_rate

    interest_expense = _to_float(report.base.interest_expense.value)
    if interest_expense is None:
        return None
    if total_debt is None or total_debt <= 0:
        return None

    derived = abs(interest_expense) / total_debt
    if derived <= 0:
        return None
    assumptions.append("cost_of_debt derived from interest_expense / total_debt")
    return derived


def _resolve_conservative_shares_denominator(
    *,
    resolved_shares_tf: TraceableField[float],
    filing_shares_tf: TraceableField[float],
    assumptions: list[str],
) -> tuple[TraceableField[float], bool]:
    resolved_value = _to_float(resolved_shares_tf.value)
    filing_value = _to_float(filing_shares_tf.value)
    if resolved_value is None or resolved_value <= 0:
        return resolved_shares_tf, False
    if filing_value is None or filing_value <= 0:
        return resolved_shares_tf, False
    if filing_value <= resolved_value:
        return resolved_shares_tf, False

    assumptions.append(
        "shares_outstanding conservative denominator policy selected filing shares "
        f"(filing={filing_value:.0f} > resolved={resolved_value:.0f})"
    )
    return filing_shares_tf, True


def _normalize_shares_source_token(shares_source: str) -> str:
    token = shares_source
    if token.endswith("_dilution_proxy"):
        token = token.removesuffix("_dilution_proxy")
    return token


def _resolve_shares_scope_from_source(shares_source: str) -> str:
    normalized = _normalize_shares_source_token(shares_source)
    if normalized == "market_data":
        return "market_class"
    return "filing_consolidated"


def _build_shares_path_diagnostics(
    *,
    selected_source: str,
    current_price: float | None,
    filing_shares: float | None,
    market_shares: float | None,
    selected_shares: float | None,
) -> _SharesPathDiagnostics:
    shares_scope = _resolve_shares_scope_from_source(selected_source)
    scope_mismatch_ratio: float | None = None
    if (
        filing_shares is not None
        and filing_shares > 0
        and market_shares is not None
        and market_shares > 0
    ):
        scope_mismatch_ratio = abs(filing_shares - market_shares) / filing_shares

    scope_mismatch_detected = bool(
        shares_scope != "market_class"
        and scope_mismatch_ratio is not None
        and scope_mismatch_ratio >= SHARES_SCOPE_MISMATCH_RATIO_THRESHOLD
        and current_price is not None
        and current_price > 0
    )

    if current_price is None or current_price <= 0:
        equity_value_scope = "unavailable_current_price"
    elif shares_scope == "market_class":
        equity_value_scope = "market_class"
    elif scope_mismatch_detected:
        equity_value_scope = "mixed_price_filing_shares"
    else:
        equity_value_scope = "filing_consolidated"

    return _SharesPathDiagnostics(
        selected_source=selected_source,
        shares_scope=shares_scope,
        equity_value_scope=equity_value_scope,
        scope_mismatch_detected=scope_mismatch_detected,
        filing_shares=filing_shares,
        market_shares=market_shares,
        selected_shares=selected_shares,
        scope_mismatch_ratio=scope_mismatch_ratio,
    )


def _resolve_s3_lite_dilution_proxy(
    *,
    report: FinancialReport,
    assumptions: list[str],
) -> float | None:
    basic_shares = _to_float(report.base.weighted_average_shares_basic.value)
    diluted_shares = _to_float(report.base.weighted_average_shares_diluted.value)

    if basic_shares is None or basic_shares <= 0:
        assumptions.append(
            "s3_lite dilution proxy fallback: weighted-average basic shares unavailable"
        )
        return None
    if diluted_shares is None or diluted_shares <= 0:
        assumptions.append(
            "s3_lite dilution proxy fallback: weighted-average diluted shares unavailable"
        )
        return None

    if diluted_shares <= basic_shares:
        assumptions.append(
            "s3_lite dilution proxy resolved to 0.00% "
            "(anti-dilutive or no incremental dilution)"
        )
        return 0.0

    raw_proxy = (diluted_shares - basic_shares) / basic_shares
    proxy = _clamp(raw_proxy, 0.0, S3_LITE_DILUTION_PROXY_CEILING)
    if proxy != raw_proxy:
        assumptions.append(
            "s3_lite dilution proxy clamped from "
            f"{raw_proxy:.2%} to {proxy:.2%} "
            f"(ceiling={S3_LITE_DILUTION_PROXY_CEILING:.2%})"
        )
    assumptions.append(
        "s3_lite dilution proxy sourced from SEC weighted-average shares "
        f"(basic={basic_shares:.0f}, diluted={diluted_shares:.0f}, proxy={proxy:.2%})"
    )
    return proxy


def _build_fcff_wacc(
    *,
    risk_free_rate: float,
    beta: float,
    market_risk_premium: float,
    tax_rate: float | None,
    total_debt: float | None,
    shares_outstanding: float | None,
    current_price: float | None,
    interest_cost_rate: float | None,
    assumptions: list[str],
) -> tuple[float, str]:
    raw_cost_of_equity = risk_free_rate + (beta * market_risk_premium)
    cost_of_equity = _clamp(raw_cost_of_equity, WACC_FLOOR, WACC_CEILING)
    if cost_of_equity != raw_cost_of_equity:
        assumptions.append(
            f"cost_of_equity clamped from {raw_cost_of_equity:.2%} to {cost_of_equity:.2%} "
            f"(bounds={WACC_FLOOR:.2%}-{WACC_CEILING:.2%})"
        )

    if (
        shares_outstanding is None
        or shares_outstanding <= 0
        or current_price is None
        or current_price <= 0
    ):
        assumptions.append(
            "wacc fallback to CAPM cost_of_equity "
            "(fcff_wacc_missing_equity_market_value)"
        )
        return cost_of_equity, (
            "Fallback CAPM cost of equity (missing equity market value for FCFF-WACC). "
            f"risk_free_rate + beta * market_risk_premium = {raw_cost_of_equity:.4f}"
        )

    equity_value = shares_outstanding * current_price
    debt_value = (
        total_debt if isinstance(total_debt, int | float) and total_debt > 0 else 0.0
    )
    if debt_value <= 0:
        assumptions.append("wacc sourced from FCFF-WACC (all-equity capital structure)")
        return cost_of_equity, (
            "FCFF-WACC all-equity path: "
            f"Ke={cost_of_equity:.4f}, E/V=1.0000, D/V=0.0000"
        )

    if interest_cost_rate is None or interest_cost_rate <= 0:
        assumptions.append(
            "wacc fallback to CAPM cost_of_equity " "(fcff_wacc_missing_cost_of_debt)"
        )
        return cost_of_equity, (
            "Fallback CAPM cost of equity (missing cost of debt for positive debt). "
            f"risk_free_rate + beta * market_risk_premium = {raw_cost_of_equity:.4f}"
        )

    cost_of_debt = _clamp(interest_cost_rate, 0.0, WACC_CEILING)
    if cost_of_debt != interest_cost_rate:
        assumptions.append(
            f"cost_of_debt clamped from {interest_cost_rate:.2%} to {cost_of_debt:.2%} "
            f"(bounds=0.00%-{WACC_CEILING:.2%})"
        )

    effective_tax_rate = _clamp(tax_rate if tax_rate is not None else 0.21, 0.0, 0.60)
    total_capital = equity_value + debt_value
    if total_capital <= 0:
        assumptions.append(
            "wacc fallback to CAPM cost_of_equity " "(fcff_wacc_non_positive_capital)"
        )
        return cost_of_equity, (
            "Fallback CAPM cost of equity (non-positive FCFF capital base). "
            f"risk_free_rate + beta * market_risk_premium = {raw_cost_of_equity:.4f}"
        )

    equity_weight = equity_value / total_capital
    debt_weight = debt_value / total_capital
    raw_wacc = (cost_of_equity * equity_weight) + (
        cost_of_debt * (1.0 - effective_tax_rate) * debt_weight
    )
    wacc = _clamp(raw_wacc, WACC_FLOOR, WACC_CEILING)
    if wacc != raw_wacc:
        assumptions.append(
            f"wacc clamped from {raw_wacc:.2%} to {wacc:.2%} "
            f"(bounds={WACC_FLOOR:.2%}-{WACC_CEILING:.2%})"
        )
    assumptions.append(
        "wacc sourced from FCFF-WACC "
        f"(ke={cost_of_equity:.2%}, kd={cost_of_debt:.2%}, "
        f"tax={effective_tax_rate:.2%}, E/V={equity_weight:.4f}, D/V={debt_weight:.4f})"
    )
    return wacc, (
        "FCFF-WACC: Ke*E/V + Kd*(1-tax)*D/V, "
        f"Ke={cost_of_equity:.4f}, Kd={cost_of_debt:.4f}, "
        f"tax={effective_tax_rate:.4f}, E/V={equity_weight:.4f}, D/V={debt_weight:.4f}, "
        f"raw={raw_wacc:.4f}"
    )


def _build_saas_capm_terminal_inputs(
    *,
    reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
    market_float: Callable[[Mapping[str, object] | None, str], float | None],
    default_market_risk_premium: float,
    tax_rate: float | None,
    total_debt: float | None,
    shares_outstanding: float | None,
    current_price: float | None,
    interest_cost_rate: float | None,
    assumptions: list[str],
) -> _SaasCapmTerminalInputs:
    market_defaults = resolve_capm_market_defaults(
        market_snapshot=market_snapshot,
        market_float=market_float,
        default_risk_free_rate=DEFAULT_SAAS_RISK_FREE_RATE,
        risk_free_format=".2%",
        default_beta=DEFAULT_SAAS_BETA,
        beta_format=".2f",
        default_market_risk_premium=default_market_risk_premium,
        market_risk_premium_format=".2%",
        allow_market_snapshot_mrp=False,
        assumptions=assumptions,
    )
    risk_free_rate = market_defaults.risk_free_rate
    raw_beta = market_defaults.beta
    beta_after_mean_reversion, beta_mean_reversion_assumption = (
        _resolve_beta_mean_reversion(
            raw_beta=raw_beta,
            market_snapshot=market_snapshot,
            filing_shares=shares_outstanding,
        )
    )
    if beta_mean_reversion_assumption is not None:
        assumptions.append(beta_mean_reversion_assumption)

    beta = _clamp(beta_after_mean_reversion, BETA_FLOOR, BETA_CEILING)
    if beta != beta_after_mean_reversion:
        assumptions.append(
            f"beta clamped from {beta_after_mean_reversion:.3f} to {beta:.3f} "
            f"(bounds={BETA_FLOOR:.3f}-{BETA_CEILING:.3f})"
        )
    market_risk_premium = market_defaults.market_risk_premium

    resolved_wacc, wacc_description = _build_fcff_wacc(
        risk_free_rate=risk_free_rate,
        beta=beta,
        market_risk_premium=market_risk_premium,
        tax_rate=tax_rate,
        total_debt=total_debt,
        shares_outstanding=shares_outstanding,
        current_price=current_price,
        interest_cost_rate=interest_cost_rate,
        assumptions=assumptions,
    )
    wacc_tf = TraceableField(
        name="WACC",
        value=resolved_wacc,
        provenance=ManualProvenance(
            description=wacc_description,
            author="ValuationPolicy",
        ),
    )

    market_anchor_raw = market_float(market_snapshot, "long_run_growth_anchor")
    market_anchor_source_detail = _extract_market_datum_source_detail(
        market_snapshot,
        field="long_run_growth_anchor",
    )
    (
        long_run_growth_anchor,
        market_anchor_basis,
        nominal_bridge_inflation,
    ) = _resolve_market_long_run_growth_anchor_nominal(
        market_anchor_raw=market_anchor_raw,
        market_anchor_source_detail=market_anchor_source_detail,
        assumptions=assumptions,
    )
    fallback_mode = _resolve_terminal_growth_stale_fallback_mode()
    assumptions.append(f"terminal_growth stale fallback mode={fallback_mode}")
    anchor_is_stale, anchor_stale_days, anchor_stale_max_days = (
        _extract_market_datum_staleness(
            market_snapshot,
            field="long_run_growth_anchor",
        )
    )
    anchor_source = "market"
    terminal_anchor = long_run_growth_anchor
    filing_anchor: float | None = None
    if anchor_is_stale is True:
        filing_anchor = _derive_filing_terminal_growth_anchor(reports)
        stale_days_label = (
            str(anchor_stale_days) if isinstance(anchor_stale_days, int) else "unknown"
        )
        stale_max_label = (
            str(anchor_stale_max_days)
            if isinstance(anchor_stale_max_days, int)
            else "unknown"
        )
        if (
            fallback_mode == TERMINAL_GROWTH_STALE_FALLBACK_FILING_FIRST
            and filing_anchor is not None
        ):
            assumptions.append(
                "terminal_growth market anchor stale; filing growth anchor "
                f"selected as terminal anchor ({filing_anchor:.2%}) "
                "(market stale: "
                f"age_days={stale_days_label}, threshold={stale_max_label})"
            )
            terminal_anchor = filing_anchor
            anchor_source = "filing"
        elif filing_anchor is not None:
            assumptions.append(
                "terminal_growth market anchor stale; filing growth anchor "
                f"captured for diagnostics only ({filing_anchor:.2%}) "
                "(market stale: "
                f"age_days={stale_days_label}, threshold={stale_max_label})"
            )
            assumptions.append(
                "terminal_growth market anchor stale; fallback to policy default "
                "(filing growth anchor is never used as terminal anchor)"
            )
            terminal_anchor = None
        else:
            assumptions.append(
                "terminal_growth market anchor stale and filing growth anchor unavailable "
                "(diagnostic only path)"
            )
            if fallback_mode == TERMINAL_GROWTH_STALE_FALLBACK_FILING_FIRST:
                assumptions.append(
                    "terminal_growth market anchor stale; filing-first fallback unavailable "
                    "(falling back to policy default)"
                )
            assumptions.append(
                "terminal_growth market anchor stale; fallback to policy default "
                "(filing growth anchor is never used as terminal anchor)"
            )
            terminal_anchor = None

    if terminal_anchor is None:
        terminal_anchor = DEFAULT_TERMINAL_GROWTH
        anchor_source = "default"

    terminal_upper_bound = min(
        TERMINAL_GROWTH_CEILING,
        resolved_wacc - TERMINAL_GROWTH_SPREAD_BUFFER,
    )
    if terminal_upper_bound <= TERMINAL_GROWTH_FLOOR:
        terminal_upper_bound = TERMINAL_GROWTH_FLOOR + 0.001
    clamped_terminal_growth = _clamp(
        terminal_anchor,
        TERMINAL_GROWTH_FLOOR,
        terminal_upper_bound,
    )
    if anchor_source == "default":
        assumptions.append(
            f"terminal_growth defaulted to {DEFAULT_TERMINAL_GROWTH:.2%} "
            "(long_run_growth_anchor unavailable)"
        )
    elif clamped_terminal_growth != terminal_anchor:
        assumptions.append(
            f"terminal_growth clamped from {terminal_anchor:.2%} to "
            f"{clamped_terminal_growth:.2%} "
            f"(bounds={TERMINAL_GROWTH_FLOOR:.2%}-{terminal_upper_bound:.2%})"
        )
    elif anchor_source == "filing":
        assumptions.append(
            "terminal_growth sourced from filing-first anchor "
            "(market stale fallback)"
        )
    else:
        assumptions.append("terminal_growth sourced from long_run_growth_anchor")
    assumptions.append(f"terminal_growth anchor source={anchor_source}")
    terminal_growth_tf = TraceableField(
        name="Terminal Growth",
        value=clamped_terminal_growth,
        provenance=ManualProvenance(
            description=(
                "Long-run-anchor terminal growth with economic bounds "
                f"(upper=min({TERMINAL_GROWTH_CEILING:.2%}, wacc-"
                f"{TERMINAL_GROWTH_SPREAD_BUFFER:.2%}))"
            ),
            author="ValuationPolicy",
        ),
    )
    terminal_growth_path = _TerminalGrowthPathDiagnostics(
        fallback_mode=fallback_mode,
        anchor_source=anchor_source,
        market_anchor_value=long_run_growth_anchor,
        market_anchor_raw_value=market_anchor_raw,
        market_anchor_basis=market_anchor_basis,
        market_anchor_source_detail=market_anchor_source_detail,
        nominal_bridge_inflation=nominal_bridge_inflation,
        filing_anchor_value=filing_anchor,
        market_anchor_is_stale=anchor_is_stale,
        market_anchor_staleness_days=anchor_stale_days,
        market_anchor_stale_max_days=anchor_stale_max_days,
    )

    return _SaasCapmTerminalInputs(
        risk_free_rate=risk_free_rate,
        beta=beta,
        market_risk_premium=market_risk_premium,
        wacc_tf=wacc_tf,
        terminal_growth_tf=terminal_growth_tf,
        terminal_growth_path=terminal_growth_path,
    )


@dataclass(frozen=True)
class _SaasOperatingRates:
    margin_tf: TraceableField[float]
    tax_rate_tf: TraceableField[float]
    da_rate_tf: TraceableField[float]
    capex_rate_tf: TraceableField[float]
    sbc_rate_tf: TraceableField[float]
    wc_rate_tf: TraceableField[float]


def _build_saas_operating_rates(
    *,
    latest: FinancialReport,
    reports: list[FinancialReport],
    revenue_tf: TraceableField[float],
    ratio: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ],
    subtract: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ],
    missing_field: Callable[[str, str], TraceableField[float]],
    assumptions: list[str],
) -> _SaasOperatingRates:
    base = latest.base
    extension = (
        latest.extension if isinstance(latest.extension, IndustrialExtension) else None
    )

    operating_income_tf = base.operating_income
    tax_expense_tf = base.income_tax_expense
    income_before_tax_tf = base.income_before_tax
    da_tf = base.depreciation_and_amortization
    sbc_tf = base.share_based_compensation
    capex_tf = extension.capex if extension else None

    margin_tf = ratio(
        "Operating Margin",
        operating_income_tf,
        revenue_tf,
        "OperatingIncome / Revenue",
    )
    tax_rate_tf = ratio(
        "Tax Rate",
        tax_expense_tf,
        income_before_tax_tf,
        "IncomeTaxExpense / IncomeBeforeTax",
    )
    if tax_rate_tf.value is None:
        tax_rate_tf = assume_rate(
            "Tax Rate",
            DEFAULT_SAAS_TAX_RATE,
            "Policy default tax rate for non-blocking missing tax inputs",
        )
        assumptions.append(f"tax_rate defaulted to {DEFAULT_SAAS_TAX_RATE:.2%}")
    da_rate_tf = ratio(
        "D&A Rate",
        da_tf,
        revenue_tf,
        "DepreciationAndAmortization / Revenue",
    )
    if da_rate_tf.value is None:
        da_rate_tf = assume_rate(
            "D&A Rate",
            DEFAULT_DA_RATE,
            "Policy default D&A rate (preview only; requires analyst review)",
        )
        assumptions.append(f"da_rates defaulted to {DEFAULT_DA_RATE:.2%}")

    capex_rate_tf = ratio_with_optional_inputs(
        name="CapEx Rate",
        numerator=capex_tf,
        denominator=revenue_tf,
        expression="CapEx / Revenue",
        missing_reason="Missing CapEx for CapEx Rate",
        ratio_op=ratio,
        missing_field_op=missing_field,
    )
    if capex_rate_tf.value is None:
        da_anchor = _to_float(da_rate_tf.value)
        capex_default = _clamp(
            max(DEFAULT_SAAS_CAPEX_RATE, da_anchor or DEFAULT_SAAS_CAPEX_RATE),
            0.0,
            0.30,
        )
        capex_rate_tf = assume_rate(
            "CapEx Rate",
            capex_default,
            "Policy default CapEx rate for non-blocking missing CapEx inputs",
        )
        assumptions.append(
            "capex_rates defaulted to " f"{capex_default:.2%} (anchor=da_rate)"
        )
    sbc_rate_tf = ratio(
        "SBC Rate",
        sbc_tf,
        revenue_tf,
        "ShareBasedCompensation / Revenue",
    )
    if sbc_rate_tf.value is None:
        sbc_rate_tf = assume_rate(
            "SBC Rate",
            DEFAULT_SAAS_SBC_RATE,
            "Policy default SBC rate for non-blocking missing SBC inputs",
        )
        assumptions.append(f"sbc_rates defaulted to {DEFAULT_SAAS_SBC_RATE:.2%}")

    current_assets_tf = base.current_assets
    current_liabilities_tf = base.current_liabilities
    wc_latest = subtract(
        "Working Capital (Latest)",
        current_assets_tf,
        current_liabilities_tf,
        "CurrentAssets - CurrentLiabilities",
    )
    wc_prev = None
    if len(reports) > 1:
        prev = reports[1]
        wc_prev = subtract(
            "Working Capital (Previous)",
            prev.base.current_assets,
            prev.base.current_liabilities,
            "Prev CurrentAssets - Prev CurrentLiabilities",
        )

    if (
        wc_prev is not None
        and wc_prev.value is not None
        and wc_latest.value is not None
    ):
        wc_delta = subtract(
            "Working Capital Delta",
            wc_latest,
            wc_prev,
            "WorkingCapitalLatest - WorkingCapitalPrevious",
        )
        wc_rate_tf = ratio("WC Rate", wc_delta, revenue_tf, "ChangeInWC / Revenue")
    else:
        wc_rate_tf = assume_rate(
            "WC Rate",
            DEFAULT_SAAS_WC_RATE,
            "Policy default WC rate for insufficient working capital history",
        )
        assumptions.append(
            "wc_rates defaulted to "
            f"{DEFAULT_SAAS_WC_RATE:.2%} (insufficient working capital history)"
        )
    if wc_rate_tf.value is None:
        wc_rate_tf = assume_rate(
            "WC Rate",
            DEFAULT_SAAS_WC_RATE,
            "Policy default WC rate for non-blocking missing WC inputs",
        )
        assumptions.append(f"wc_rates defaulted to {DEFAULT_SAAS_WC_RATE:.2%}")

    return _SaasOperatingRates(
        margin_tf=margin_tf,
        tax_rate_tf=tax_rate_tf,
        da_rate_tf=da_rate_tf,
        capex_rate_tf=capex_rate_tf,
        sbc_rate_tf=sbc_rate_tf,
        wc_rate_tf=wc_rate_tf,
    )


def _collect_saas_missing_metric_names(
    *,
    growth_rates_tf: TraceableField[list[float]],
    operating_margins_tf: TraceableField[list[float]],
    tax_rate_tf: TraceableField[float],
    da_rates_tf: TraceableField[list[float]],
    capex_rates_tf: TraceableField[list[float]],
    wc_rates_tf: TraceableField[list[float]],
    sbc_rates_tf: TraceableField[list[float]],
) -> list[str]:
    return collect_missing_metric_names(
        metric_fields={
            "growth_rates": growth_rates_tf,
            "operating_margins": operating_margins_tf,
            "tax_rate": tax_rate_tf,
            "da_rates": da_rates_tf,
            "capex_rates": capex_rates_tf,
            "wc_rates": wc_rates_tf,
            "sbc_rates": sbc_rates_tf,
        }
    )


def _build_saas_trace_inputs(
    *,
    revenue_tf: TraceableField[float],
    growth_rates_tf: TraceableField[list[float]],
    operating_margins_tf: TraceableField[list[float]],
    tax_rate_tf: TraceableField[float],
    da_rates_tf: TraceableField[list[float]],
    capex_rates_tf: TraceableField[list[float]],
    wc_rates_tf: TraceableField[list[float]],
    sbc_rates_tf: TraceableField[list[float]],
    wacc_tf: TraceableField[float],
    terminal_growth_tf: TraceableField[float],
    risk_free_rate: float,
    beta: float,
    market_risk_premium: float,
    cash_tf: TraceableField[float],
    debt_tf: TraceableField[float],
    preferred_tf: TraceableField[float],
    shares_tf: TraceableField[float],
) -> dict[str, TraceInput]:
    return {
        "initial_revenue": revenue_tf,
        "growth_rates": growth_rates_tf,
        "operating_margins": operating_margins_tf,
        "tax_rate": tax_rate_tf,
        "da_rates": da_rates_tf,
        "capex_rates": capex_rates_tf,
        "wc_rates": wc_rates_tf,
        "sbc_rates": sbc_rates_tf,
        "wacc": wacc_tf,
        "terminal_growth": terminal_growth_tf,
        **build_capm_market_trace_inputs(
            risk_free_rate=risk_free_rate,
            beta=beta,
            market_risk_premium=market_risk_premium,
            risk_free_description="Market-derived risk-free rate for SaaS CAPM",
            beta_description="Market-derived beta for SaaS CAPM",
            market_risk_premium_description="Policy market risk premium for SaaS CAPM",
        ),
        **build_capital_structure_trace_inputs(
            cash_tf=cash_tf,
            debt_tf=debt_tf,
            preferred_tf=preferred_tf,
            shares_tf=shares_tf,
        ),
    }


def _build_saas_rationale(assumptions: list[str]) -> str:
    rationale = "Derived from SEC XBRL (financial reports) with computed rates."
    if assumptions:
        rationale += " Controlled assumptions applied: " + "; ".join(assumptions)
    return rationale


def _build_saas_params(
    *,
    ticker: str | None,
    rationale: str,
    initial_revenue: float | None,
    growth_rates: list[float] | None,
    operating_margins: list[float] | None,
    tax_rate: float | None,
    da_rates: list[float] | None,
    capex_rates: list[float] | None,
    wc_rates: list[float] | None,
    sbc_rates: list[float] | None,
    wacc: float | None,
    terminal_growth: float | None,
    risk_free_rate: float,
    beta: float,
    market_risk_premium: float,
    shares_outstanding: float | None,
    cash: float | None,
    total_debt: float | None,
    preferred_stock: float | None,
    current_price: float | None,
    monte_carlo_iterations: int,
    monte_carlo_seed: int | None,
    monte_carlo_sampler: str,
) -> dict[str, object]:
    return {
        **build_base_params(
            ticker=ticker,
            rationale=rationale,
        ),
        "initial_revenue": initial_revenue,
        "growth_rates": growth_rates,
        "operating_margins": operating_margins,
        "tax_rate": tax_rate,
        "da_rates": da_rates,
        "capex_rates": capex_rates,
        "wc_rates": wc_rates,
        "sbc_rates": sbc_rates,
        "wacc": wacc,
        "terminal_growth": terminal_growth,
        **build_capm_market_params(
            risk_free_rate=risk_free_rate,
            beta=beta,
            market_risk_premium=market_risk_premium,
        ),
        **build_capital_structure_params(
            cash=cash,
            total_debt=total_debt,
            preferred_stock=preferred_stock,
            shares_outstanding=shares_outstanding,
            current_price=current_price,
        ),
        **build_monte_carlo_params(
            monte_carlo_iterations=monte_carlo_iterations,
            monte_carlo_seed=monte_carlo_seed,
            monte_carlo_sampler=monte_carlo_sampler,
        ),
    }


@dataclass(frozen=True)
class SaasBuilderDeps:
    projection_years: int
    default_market_risk_premium: float
    resolve_shares_outstanding: Callable[
        [TraceableField[float], Mapping[str, object] | None, list[str]],
        TraceableField[float],
    ]
    market_float: Callable[[Mapping[str, object] | None, str], float | None]
    value_or_missing: Callable[
        [TraceableField[float] | None, str, list[str]],
        float | None,
    ]
    ratio: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ]
    subtract: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ]
    build_growth_rates: Callable[
        [list[TraceableField[float]], Mapping[str, object] | None, list[str]],
        TraceableField[list[float]],
    ]
    repeat_rate: Callable[
        [str, TraceableField[float], int], TraceableField[list[float]]
    ]
    resolve_monte_carlo_controls: Callable[
        [Mapping[str, object] | None, list[str]],
        MonteCarloControls,
    ]
    missing_field: Callable[[str, str], TraceableField[float]]


@dataclass(frozen=True)
class SaasBuildPayload:
    params: dict[str, object]
    trace_inputs: dict[str, TraceInput]
    missing: list[str]
    assumptions: list[str]
    shares_source: str
    terminal_growth_path: dict[str, object] | None = None
    shares_path: dict[str, object] | None = None


def build_saas_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
    deps: SaasBuilderDeps,
) -> SaasBuildPayload:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base

    revenue_tf = base.total_revenue
    filing_shares = _to_float(base.shares_outstanding.value)
    market_shares = _to_float(deps.market_float(market_snapshot, "shares_outstanding"))
    shares_tf = deps.resolve_shares_outstanding(
        base.shares_outstanding,
        market_snapshot,
        assumptions,
    )
    shares_tf, used_filing_conservative_shares = (
        _resolve_conservative_shares_denominator(
            resolved_shares_tf=shares_tf,
            filing_shares_tf=base.shares_outstanding,
            assumptions=assumptions,
        )
    )
    cash_tf = base.cash_and_equivalents
    debt_tf = base.total_debt
    preferred_tf = base.preferred_stock

    operating_rates = _build_saas_operating_rates(
        latest=latest,
        reports=reports,
        revenue_tf=revenue_tf,
        ratio=deps.ratio,
        subtract=deps.subtract,
        missing_field=deps.missing_field,
        assumptions=assumptions,
    )
    margin_tf = operating_rates.margin_tf
    tax_rate_tf = operating_rates.tax_rate_tf
    da_rate_tf = operating_rates.da_rate_tf
    capex_rate_tf = operating_rates.capex_rate_tf
    sbc_rate_tf = operating_rates.sbc_rate_tf
    wc_rate_tf = operating_rates.wc_rate_tf

    revenue_series = [report.base.total_revenue for report in reports]
    growth_rates_tf = deps.build_growth_rates(
        revenue_series, market_snapshot, assumptions
    )

    operating_margins_tf = deps.repeat_rate(
        "Operating Margins", margin_tf, deps.projection_years
    )
    da_rates_tf = deps.repeat_rate("D&A Rates", da_rate_tf, deps.projection_years)
    capex_rates_tf = deps.repeat_rate(
        "CapEx Rates", capex_rate_tf, deps.projection_years
    )
    wc_rates_tf = deps.repeat_rate("WC Rates", wc_rate_tf, deps.projection_years)
    sbc_rates_tf = deps.repeat_rate("SBC Rates", sbc_rate_tf, deps.projection_years)

    initial_revenue = deps.value_or_missing(
        revenue_tf,
        "initial_revenue",
        missing,
    )
    market_values = extract_filing_capital_structure_market_values(
        value_or_missing=deps.value_or_missing,
        missing=missing,
        shares_tf=shares_tf,
        cash_tf=cash_tf,
        debt_tf=debt_tf,
        preferred_tf=preferred_tf,
        market_float=deps.market_float,
        market_snapshot=market_snapshot,
    )
    shares_outstanding = market_values.shares_outstanding
    cash = market_values.cash
    total_debt = market_values.total_debt
    preferred_stock = market_values.preferred_stock
    current_price = market_values.current_price
    shares_source = market_values.shares_source
    if used_filing_conservative_shares and shares_source == "market_data":
        shares_source = "filing_conservative_dilution"

    dilution_proxy = _resolve_s3_lite_dilution_proxy(
        report=latest,
        assumptions=assumptions,
    )
    if dilution_proxy is not None:
        if shares_outstanding is None or shares_outstanding <= 0:
            assumptions.append(
                "s3_lite dilution proxy skipped: shares_outstanding unavailable"
            )
        elif dilution_proxy <= 0:
            assumptions.append(
                "s3_lite dilution proxy not applied to denominator (proxy=0.00%)"
            )
        else:
            adjusted_shares_outstanding = shares_outstanding * (1.0 + dilution_proxy)
            assumptions.append(
                "shares_outstanding adjusted by s3_lite dilution proxy "
                f"(base={shares_outstanding:.0f}, proxy={dilution_proxy:.2%}, "
                f"adjusted={adjusted_shares_outstanding:.0f})"
            )
            shares_outstanding = adjusted_shares_outstanding
            shares_source = (
                shares_source
                if shares_source.endswith("_dilution_proxy")
                else f"{shares_source}_dilution_proxy"
            )
            shares_tf = TraceableField(
                name="Shares Outstanding (S3-lite Dilution Proxy)",
                value=shares_outstanding,
                provenance=ManualProvenance(
                    description=(
                        "Denominator adjusted by SEC weighted-average "
                        f"dilution proxy ({dilution_proxy:.4f})"
                    ),
                    author="ValuationPolicy",
                ),
            )
    shares_path_diagnostics = _build_shares_path_diagnostics(
        selected_source=shares_source,
        current_price=current_price,
        filing_shares=filing_shares,
        market_shares=market_shares,
        selected_shares=shares_outstanding,
    )
    if shares_path_diagnostics.scope_mismatch_detected:
        mismatch_ratio = shares_path_diagnostics.scope_mismatch_ratio
        if mismatch_ratio is not None:
            assumptions.append(
                "shares_scope mismatch detected "
                f"(shares_scope={shares_path_diagnostics.shares_scope}, "
                f"equity_value_scope={shares_path_diagnostics.equity_value_scope}, "
                f"mismatch_ratio={mismatch_ratio:.2%})"
            )
    (
        monte_carlo_iterations,
        monte_carlo_seed,
        monte_carlo_sampler,
    ) = deps.resolve_monte_carlo_controls(market_snapshot, assumptions)

    missing_policy = apply_missing_metric_policy(
        missing_fields=_collect_saas_missing_metric_names(
            growth_rates_tf=growth_rates_tf,
            operating_margins_tf=operating_margins_tf,
            tax_rate_tf=tax_rate_tf,
            da_rates_tf=da_rates_tf,
            capex_rates_tf=capex_rates_tf,
            wc_rates_tf=wc_rates_tf,
            sbc_rates_tf=sbc_rates_tf,
        ),
        warn_only_fields=_SAAS_WARN_ONLY_MISSING_METRICS,
    )
    if missing_policy.warn_only_fields:
        assumptions.append(
            "xbrl_missing_input_policy downgraded non-critical metrics to warn "
            f"(fields={sorted(set(missing_policy.warn_only_fields))})"
        )
    missing.extend(missing_policy.blocking_fields)

    capm_terminal_inputs = _build_saas_capm_terminal_inputs(
        reports=reports,
        market_snapshot=market_snapshot,
        market_float=deps.market_float,
        default_market_risk_premium=deps.default_market_risk_premium,
        tax_rate=tax_rate_tf.value,
        total_debt=total_debt,
        shares_outstanding=shares_outstanding,
        current_price=current_price,
        interest_cost_rate=_resolve_interest_cost_rate(
            report=latest,
            total_debt=total_debt,
            assumptions=assumptions,
        ),
        assumptions=assumptions,
    )
    risk_free_rate = capm_terminal_inputs.risk_free_rate
    beta = capm_terminal_inputs.beta
    market_risk_premium = capm_terminal_inputs.market_risk_premium
    wacc_tf = capm_terminal_inputs.wacc_tf
    terminal_growth_tf = capm_terminal_inputs.terminal_growth_tf

    trace_inputs: dict[str, TraceInput] = _build_saas_trace_inputs(
        revenue_tf=revenue_tf,
        growth_rates_tf=growth_rates_tf,
        operating_margins_tf=operating_margins_tf,
        tax_rate_tf=tax_rate_tf,
        da_rates_tf=da_rates_tf,
        capex_rates_tf=capex_rates_tf,
        wc_rates_tf=wc_rates_tf,
        sbc_rates_tf=sbc_rates_tf,
        wacc_tf=wacc_tf,
        terminal_growth_tf=terminal_growth_tf,
        risk_free_rate=risk_free_rate,
        beta=beta,
        market_risk_premium=market_risk_premium,
        cash_tf=cash_tf,
        debt_tf=debt_tf,
        preferred_tf=preferred_tf,
        shares_tf=shares_tf,
    )

    rationale = _build_saas_rationale(assumptions)
    params: dict[str, object] = _build_saas_params(
        ticker=ticker,
        rationale=rationale,
        initial_revenue=initial_revenue,
        growth_rates=growth_rates_tf.value,
        operating_margins=operating_margins_tf.value,
        tax_rate=tax_rate_tf.value,
        da_rates=da_rates_tf.value,
        capex_rates=capex_rates_tf.value,
        wc_rates=wc_rates_tf.value,
        sbc_rates=sbc_rates_tf.value,
        wacc=wacc_tf.value,
        terminal_growth=terminal_growth_tf.value,
        risk_free_rate=risk_free_rate,
        beta=beta,
        market_risk_premium=market_risk_premium,
        shares_outstanding=shares_outstanding,
        cash=cash,
        total_debt=total_debt,
        preferred_stock=preferred_stock,
        current_price=current_price,
        monte_carlo_iterations=monte_carlo_iterations,
        monte_carlo_seed=monte_carlo_seed,
        monte_carlo_sampler=monte_carlo_sampler,
    )

    return SaasBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=missing,
        assumptions=assumptions,
        shares_source=shares_source,
        terminal_growth_path=capm_terminal_inputs.terminal_growth_path.to_metadata(),
        shares_path=shares_path_diagnostics.to_metadata(),
    )
