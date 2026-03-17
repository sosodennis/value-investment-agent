from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from src.agents.technical.domain.shared import (
    FeatureFrame,
    FeaturePack,
    IndicatorSnapshot,
    PriceSeries,
    TimeframeCode,
)
from src.agents.technical.subdomains.features.application.feature_dependency_dag import (
    FeatureDagIssue,
    FeatureExecutionContext,
    FeatureTask,
    build_feature_execution_plan,
)
from src.agents.technical.subdomains.features.application.ports import IIndicatorEngine
from src.agents.technical.subdomains.features.domain import (
    calculate_fd_bollinger,
    calculate_fd_obv,
    calculate_rolling_fracdiff,
    calculate_rolling_z_score,
    calculate_statistical_strength,
    compute_adx,
    compute_atr,
    compute_atrp,
    compute_bollinger_bandwidth,
    compute_ema,
    compute_macd,
    compute_mfi,
    compute_rsi,
    compute_sma,
    compute_vwap,
    compute_z_score,
)
from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)

CLASSIC_STAGE = "classic"
QUANT_STAGE = "quant"
FEATURE_STAGE_ORDER = (CLASSIC_STAGE, QUANT_STAGE)


@dataclass(frozen=True)
class FeatureRuntimeRequest:
    ticker: str
    as_of: str
    series_by_timeframe: dict[TimeframeCode, PriceSeries]


@dataclass(frozen=True)
class FeatureRuntimeResult:
    feature_pack: FeaturePack
    degraded_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FeatureRuntimeService:
    quant_timeframes: tuple[TimeframeCode, ...] = ("1d",)
    min_quant_points: int = 300
    indicator_engine: IIndicatorEngine | None = None

    def compute(self, request: FeatureRuntimeRequest) -> FeatureRuntimeResult:
        frames: dict[TimeframeCode, FeatureFrame] = {}
        degraded: list[str] = []

        for timeframe, series in request.series_by_timeframe.items():
            price_series = _build_series(series.price_series)
            volume_series = _build_series(series.volume_series)
            high_series = _build_series(series.high_series)
            low_series = _build_series(series.low_series)
            if price_series.empty:
                degraded.append(f"{timeframe}_PRICE_EMPTY")
                frames[timeframe] = FeatureFrame()
                continue

            latest_price = _safe_float(price_series.iloc[-1])
            ctx = FeatureExecutionContext(
                price_series=price_series,
                volume_series=volume_series,
                high_series=high_series,
                low_series=low_series,
                latest_price=latest_price,
            )

            include_quant = (
                timeframe in self.quant_timeframes
                and len(price_series) >= self.min_quant_points
            )
            if not include_quant:
                ctx.degraded.append("QUANT_SKIPPED")

            engine = self.indicator_engine
            if engine is not None:
                availability = engine.availability()
                if not availability.available:
                    ctx.degraded.append(
                        availability.reason or "CLASSIC_ENGINE_UNAVAILABLE"
                    )
                    engine = None

            tasks = _build_tasks(include_quant=include_quant, indicator_engine=engine)
            plan = build_feature_execution_plan(tasks, stage_order=FEATURE_STAGE_ORDER)
            if plan.issues:
                ctx.degraded.extend(
                    _record_dag_issues(request.ticker, timeframe, plan.issues)
                )

            for task in plan.ordered_tasks:
                task.run(ctx)

            frames[timeframe] = _build_feature_frame(ctx)
            degraded.extend([f"{timeframe}_{reason}" for reason in ctx.degraded])

        feature_pack = FeaturePack(
            ticker=request.ticker,
            as_of=request.as_of,
            timeframes=frames,
            feature_summary=_build_feature_summary(frames),
        )
        return FeatureRuntimeResult(
            feature_pack=feature_pack, degraded_reasons=degraded
        )


def _record_dag_issues(
    ticker: str, timeframe: TimeframeCode, issues: list[FeatureDagIssue]
) -> list[str]:
    if not issues:
        return []
    codes = [issue.code for issue in issues]
    log_event(
        logger,
        event="technical_feature_dag_invalid",
        message="technical feature DAG validation reported issues",
        error_code="TECHNICAL_FEATURE_DAG_INVALID",
        fields={
            "ticker": ticker,
            "timeframe": timeframe,
            "issue_codes": codes,
            "issue_count": len(issues),
            "issue_messages": [issue.message for issue in issues],
        },
    )
    return codes


def _build_tasks(
    *,
    include_quant: bool,
    indicator_engine: IIndicatorEngine | None,
) -> list[FeatureTask]:
    tasks: list[FeatureTask] = []
    if indicator_engine is None:
        tasks.extend(
            [
                FeatureTask(name="SMA_20", stage=CLASSIC_STAGE, run=_task_sma_20),
                FeatureTask(name="EMA_20", stage=CLASSIC_STAGE, run=_task_ema_20),
                FeatureTask(name="RSI_14", stage=CLASSIC_STAGE, run=_task_rsi_14),
                FeatureTask(name="MACD", stage=CLASSIC_STAGE, run=_task_macd),
                FeatureTask(name="VWAP", stage=CLASSIC_STAGE, run=_task_vwap),
                FeatureTask(name="MFI_14", stage=CLASSIC_STAGE, run=_task_mfi_14),
                FeatureTask(name="ATR_14", stage=CLASSIC_STAGE, run=_task_atr_14),
                FeatureTask(name="ADX_14", stage=CLASSIC_STAGE, run=_task_adx_14),
                FeatureTask(name="ATRP_14", stage=CLASSIC_STAGE, run=_task_atrp_14),
                FeatureTask(
                    name="BB_BANDWIDTH_20",
                    stage=CLASSIC_STAGE,
                    run=_task_bb_bandwidth_20,
                ),
            ]
        )
    else:
        tasks.append(
            FeatureTask(
                name="CLASSIC_ENGINE",
                stage=CLASSIC_STAGE,
                run=_make_classic_engine_task(indicator_engine),
            )
        )

    if include_quant:
        tasks.extend(
            [
                FeatureTask(name="FD_BASE", stage=QUANT_STAGE, run=_task_fd_base),
                FeatureTask(
                    name="FD_BOLLINGER_BW",
                    stage=QUANT_STAGE,
                    run=_task_fd_bollinger_bw,
                    dependencies=("FD_BASE",),
                ),
                FeatureTask(
                    name="FD_OBV_Z",
                    stage=QUANT_STAGE,
                    run=_task_fd_obv_z,
                    dependencies=("FD_BASE",),
                ),
            ]
        )

    return tasks


def _make_classic_engine_task(engine: IIndicatorEngine):
    def _task(ctx: FeatureExecutionContext) -> None:
        result = engine.compute_classic_indicators(
            price_series=ctx.price_series,
            high_series=ctx.high_series,
            low_series=ctx.low_series,
            volume_series=ctx.volume_series,
            latest_price=ctx.latest_price,
        )
        for name, snapshot in result.indicators.items():
            ctx.add_output(name, snapshot, CLASSIC_STAGE)
        ctx.degraded.extend(result.degraded_reasons)

    return _task


def _build_feature_frame(ctx: FeatureExecutionContext) -> FeatureFrame:
    classic: dict[str, IndicatorSnapshot] = {}
    quant: dict[str, IndicatorSnapshot] = {}
    for name, snapshot in ctx.outputs.items():
        stage = ctx.output_stages.get(name)
        if stage == CLASSIC_STAGE:
            classic[name] = snapshot
        elif stage == QUANT_STAGE:
            quant[name] = snapshot
    return FeatureFrame(classic_indicators=classic, quant_features=quant)


def _task_sma_20(ctx: FeatureExecutionContext) -> None:
    sma_20 = compute_sma(ctx.price_series, window=20)
    sma_val = _latest_value(sma_20)
    ctx.add_output(
        "SMA_20",
        _snapshot("SMA_20", sma_val, state=_compare_state(ctx.latest_price, sma_val)),
        CLASSIC_STAGE,
    )


def _task_ema_20(ctx: FeatureExecutionContext) -> None:
    ema_20 = compute_ema(ctx.price_series, window=20)
    ema_val = _latest_value(ema_20)
    ctx.add_output(
        "EMA_20",
        _snapshot("EMA_20", ema_val, state=_compare_state(ctx.latest_price, ema_val)),
        CLASSIC_STAGE,
    )


def _task_rsi_14(ctx: FeatureExecutionContext) -> None:
    rsi = compute_rsi(ctx.price_series, window=14)
    rsi_val = _latest_value(rsi)
    ctx.add_output(
        "RSI_14",
        _snapshot("RSI_14", rsi_val, state=_momentum_state(rsi_val)),
        CLASSIC_STAGE,
    )


def _task_macd(ctx: FeatureExecutionContext) -> None:
    macd_line, signal_line, hist = compute_macd(ctx.price_series)
    macd_val = _latest_value(macd_line)
    signal_val = _latest_value(signal_line)
    hist_val = _latest_value(hist)
    ctx.add_output(
        "MACD",
        _snapshot(
            "MACD",
            macd_val,
            state=_macd_state(macd_val, signal_val),
            metadata={
                "signal": _safe_float(signal_val),
                "hist": _safe_float(hist_val),
            },
        ),
        CLASSIC_STAGE,
    )


def _task_vwap(ctx: FeatureExecutionContext) -> None:
    if ctx.volume_series.empty:
        ctx.add_output(
            "VWAP",
            _snapshot(
                "VWAP", None, state="UNAVAILABLE", metadata={"reason": "missing_volume"}
            ),
            CLASSIC_STAGE,
        )
        return

    vwap_series = compute_vwap(ctx.price_series, ctx.volume_series)
    vwap_val = _latest_value(vwap_series)
    ctx.add_output(
        "VWAP",
        _snapshot("VWAP", vwap_val, state=_compare_state(ctx.latest_price, vwap_val)),
        CLASSIC_STAGE,
    )


def _task_mfi_14(ctx: FeatureExecutionContext) -> None:
    if ctx.volume_series.empty:
        ctx.add_output(
            "MFI_14",
            _snapshot(
                "MFI_14",
                None,
                state="UNAVAILABLE",
                metadata={"reason": "missing_volume"},
            ),
            CLASSIC_STAGE,
        )
        return

    mfi_series = compute_mfi(ctx.price_series, ctx.volume_series, window=14)
    mfi_val = _latest_value(mfi_series)
    ctx.add_output(
        "MFI_14",
        _snapshot("MFI_14", mfi_val, state=_momentum_state(mfi_val)),
        CLASSIC_STAGE,
    )


def _task_atr_14(ctx: FeatureExecutionContext) -> None:
    if ctx.high_series.empty or ctx.low_series.empty:
        ctx.add_output(
            "ATR_14",
            _snapshot(
                "ATR_14",
                None,
                state="UNAVAILABLE",
                metadata={"reason": "missing_high_low"},
            ),
            CLASSIC_STAGE,
        )
        return

    atr_series = compute_atr(
        ctx.high_series,
        ctx.low_series,
        ctx.price_series,
        window=14,
    )
    atr_val = _latest_value(atr_series) if atr_series is not None else None
    ctx.add_output(
        "ATR_14",
        _snapshot(
            "ATR_14",
            atr_val,
            state="UNAVAILABLE" if atr_series is None else None,
        ),
        CLASSIC_STAGE,
    )


def _task_adx_14(ctx: FeatureExecutionContext) -> None:
    if ctx.high_series.empty or ctx.low_series.empty:
        ctx.add_output(
            "ADX_14",
            _snapshot(
                "ADX_14",
                None,
                state="UNAVAILABLE",
                metadata={"reason": "missing_high_low"},
            ),
            CLASSIC_STAGE,
        )
        return

    adx_series = compute_adx(
        ctx.high_series,
        ctx.low_series,
        ctx.price_series,
        window=14,
    )
    adx_val = _latest_value(adx_series)
    ctx.add_output(
        "ADX_14",
        _snapshot("ADX_14", adx_val, state=_adx_state(adx_val)),
        CLASSIC_STAGE,
    )


def _task_atrp_14(ctx: FeatureExecutionContext) -> None:
    if ctx.high_series.empty or ctx.low_series.empty:
        ctx.add_output(
            "ATRP_14",
            _snapshot(
                "ATRP_14",
                None,
                state="UNAVAILABLE",
                metadata={"reason": "missing_high_low"},
            ),
            CLASSIC_STAGE,
        )
        return

    atrp_series = compute_atrp(
        ctx.high_series,
        ctx.low_series,
        ctx.price_series,
        window=14,
    )
    atrp_val = _latest_value(atrp_series)
    ctx.add_output(
        "ATRP_14",
        _snapshot("ATRP_14", atrp_val, state=_atrp_state(atrp_val)),
        CLASSIC_STAGE,
    )


def _task_bb_bandwidth_20(ctx: FeatureExecutionContext) -> None:
    bandwidth_series = compute_bollinger_bandwidth(
        ctx.price_series,
        window=20,
        num_std=2.0,
    )
    bandwidth_val = _latest_value(bandwidth_series)
    ctx.add_output(
        "BB_BANDWIDTH_20",
        _snapshot(
            "BB_BANDWIDTH_20",
            bandwidth_val,
            state=_bandwidth_state(bandwidth_val),
        ),
        CLASSIC_STAGE,
    )


def _task_fd_base(ctx: FeatureExecutionContext) -> None:
    fd_series, optimal_d, _, adf_stat, adf_pvalue = calculate_rolling_fracdiff(
        ctx.price_series,
        lookback_window=252,
        recalc_step=5,
    )
    if fd_series.empty:
        ctx.degraded.append("FRACDIFF_EMPTY")
        return

    ctx.cache["fd_series"] = fd_series

    z_score_latest = compute_z_score(fd_series, lookback=252)
    z_score_series = calculate_rolling_z_score(fd_series, lookback=252)
    stat_strength = calculate_statistical_strength(z_score_series)

    ctx.cache["fd_z_score_series"] = z_score_series
    ctx.cache["fd_stat_strength"] = stat_strength
    ctx.cache["fd_optimal_d"] = optimal_d
    ctx.cache["fd_adf_stat"] = adf_stat
    ctx.cache["fd_adf_pvalue"] = adf_pvalue

    ctx.add_output(
        "FD_Z_SCORE",
        _snapshot("FD_Z_SCORE", z_score_latest, state=_zscore_state(z_score_latest)),
        QUANT_STAGE,
    )
    ctx.add_output("FD_OPTIMAL_D", _snapshot("FD_OPTIMAL_D", optimal_d), QUANT_STAGE)
    ctx.add_output("FD_ADF_STAT", _snapshot("FD_ADF_STAT", adf_stat), QUANT_STAGE)
    ctx.add_output("FD_ADF_PVALUE", _snapshot("FD_ADF_PVALUE", adf_pvalue), QUANT_STAGE)
    ctx.add_output(
        "FD_STAT_STRENGTH",
        _snapshot("FD_STAT_STRENGTH", stat_strength.get("value")),
        QUANT_STAGE,
    )


def _task_fd_bollinger_bw(ctx: FeatureExecutionContext) -> None:
    fd_series = ctx.cache.get("fd_series")
    if not isinstance(fd_series, pd.Series) or fd_series.empty:
        ctx.degraded.append("FD_BOLLINGER_MISSING_BASE")
        return

    bollinger = calculate_fd_bollinger(fd_series)
    ctx.add_output(
        "FD_BOLLINGER_BW",
        _snapshot(
            "FD_BOLLINGER_BW",
            bollinger.get("bandwidth"),
            state=str(bollinger.get("state") or "INSIDE"),
            metadata={
                "upper": _safe_float(bollinger.get("upper")),
                "lower": _safe_float(bollinger.get("lower")),
            },
        ),
        QUANT_STAGE,
    )


def _task_fd_obv_z(ctx: FeatureExecutionContext) -> None:
    fd_series = ctx.cache.get("fd_series")
    if not isinstance(fd_series, pd.Series) or fd_series.empty:
        ctx.degraded.append("FD_OBV_MISSING_BASE")
        return
    if ctx.volume_series.empty:
        ctx.degraded.append("FD_OBV_MISSING_VOLUME")
        return

    obv_data = calculate_fd_obv(ctx.price_series, ctx.volume_series)
    ctx.add_output(
        "FD_OBV_Z",
        _snapshot(
            "FD_OBV_Z",
            obv_data.get("fd_obv_z"),
            state=str(obv_data.get("state") or "NEUTRAL"),
            metadata={"optimal_d": _safe_float(obv_data.get("optimal_d"))},
        ),
        QUANT_STAGE,
    )


def _build_series(raw_series: dict[str, float | int | None]) -> pd.Series:
    if not raw_series:
        return pd.Series(dtype=float)
    series = pd.Series(raw_series)
    try:
        series.index = pd.to_datetime(series.index)
    except Exception:
        pass
    series = series.sort_index()
    series = pd.to_numeric(series, errors="coerce")
    series = series.replace([math.inf, -math.inf], math.nan)
    return series.dropna()


def _safe_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _snapshot(
    name: str,
    value: float | int | None,
    *,
    state: str | None = None,
    metadata: dict[str, float | int | str | bool | None] | None = None,
) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        name=name,
        value=_safe_float(value),
        state=state,
        metadata=metadata or {},
    )


def _latest_value(series: pd.Series | None) -> float | None:
    if series is None or series.empty:
        return None
    return _safe_float(series.iloc[-1])


def _compare_state(latest_price: float | None, reference: float | None) -> str | None:
    if latest_price is None or reference is None:
        return "UNAVAILABLE"
    if latest_price > reference:
        return "ABOVE"
    if latest_price < reference:
        return "BELOW"
    return "NEUTRAL"


def _momentum_state(value: float | None) -> str | None:
    if value is None:
        return "UNAVAILABLE"
    if value >= 70.0:
        return "OVERBOUGHT"
    if value <= 30.0:
        return "OVERSOLD"
    return "NEUTRAL"


def _macd_state(macd_val: float | None, signal_val: float | None) -> str | None:
    if macd_val is None or signal_val is None:
        return "UNAVAILABLE"
    if macd_val > signal_val:
        return "BULLISH"
    if macd_val < signal_val:
        return "BEARISH"
    return "NEUTRAL"


def _adx_state(value: float | None) -> str | None:
    if value is None:
        return "UNAVAILABLE"
    if value >= 25.0:
        return "TRENDING"
    if value <= 15.0:
        return "RANGING"
    return "NEUTRAL"


def _atrp_state(value: float | None) -> str | None:
    if value is None:
        return "UNAVAILABLE"
    if value >= 0.035:
        return "EXPANDING"
    if value <= 0.015:
        return "COMPRESSED"
    return "NEUTRAL"


def _bandwidth_state(value: float | None) -> str | None:
    if value is None:
        return "UNAVAILABLE"
    if value >= 0.12:
        return "EXPANDING"
    if value <= 0.08:
        return "COMPRESSED"
    return "NEUTRAL"


def _zscore_state(z_score: float | None) -> str | None:
    if z_score is None:
        return "UNAVAILABLE"
    if z_score >= 2.0:
        return "EXTREME_POSITIVE"
    if z_score <= -2.0:
        return "EXTREME_NEGATIVE"
    return "NEUTRAL"


def _build_feature_summary(
    frames: dict[TimeframeCode, FeatureFrame],
) -> dict[str, float | int | str | bool | None]:
    classic_total = sum(len(frame.classic_indicators) for frame in frames.values())
    quant_total = sum(len(frame.quant_features) for frame in frames.values())
    return {
        "classic_count": classic_total,
        "quant_count": quant_total,
        "timeframe_count": len(frames),
    }
