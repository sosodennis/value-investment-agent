from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from src.agents.technical.domain.shared import (
    FeatureFrame,
    FeaturePack,
    FeatureSummary,
    IndicatorProvenance,
    IndicatorQuality,
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
    supports_session_vwap_timeframe,
)
from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)

CLASSIC_STAGE = "classic"
QUANT_STAGE = "quant"
FEATURE_STAGE_ORDER = (CLASSIC_STAGE, QUANT_STAGE)
FEATURE_CALCULATION_VERSION = "technical_feature_contract_v1"
_REGIME_INPUT_SIGNALS = frozenset({"ATR_14", "ATRP_14", "ADX_14", "BB_BANDWIDTH_20"})


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
                timeframe=timeframe,
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
            timeframe=ctx.timeframe,
            price_series=ctx.price_series,
            high_series=ctx.high_series,
            low_series=ctx.low_series,
            volume_series=ctx.volume_series,
            latest_price=ctx.latest_price,
        )
        for name, snapshot in result.indicators.items():
            ctx.add_output(
                name, _ensure_snapshot_contract(ctx, snapshot), CLASSIC_STAGE
            )
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
        _snapshot(
            "SMA_20",
            sma_val,
            timeframe=ctx.timeframe,
            state=_compare_state(ctx.latest_price, sma_val),
            minimum_samples=20,
            input_basis="close",
            method="sma_20",
            metadata={"effective_sample_count": len(ctx.price_series)},
        ),
        CLASSIC_STAGE,
    )


def _task_ema_20(ctx: FeatureExecutionContext) -> None:
    ema_20 = compute_ema(ctx.price_series, window=20)
    ema_val = _latest_value(ema_20)
    ctx.add_output(
        "EMA_20",
        _snapshot(
            "EMA_20",
            ema_val,
            timeframe=ctx.timeframe,
            state=_compare_state(ctx.latest_price, ema_val),
            minimum_samples=20,
            input_basis="close",
            method="ema_20",
            metadata={"effective_sample_count": len(ctx.price_series)},
        ),
        CLASSIC_STAGE,
    )


def _task_rsi_14(ctx: FeatureExecutionContext) -> None:
    rsi = compute_rsi(ctx.price_series, window=14)
    rsi_val = _latest_value(rsi)
    ctx.add_output(
        "RSI_14",
        _snapshot(
            "RSI_14",
            rsi_val,
            timeframe=ctx.timeframe,
            state=_momentum_state(rsi_val),
            minimum_samples=14,
            input_basis="close",
            method="rsi_14",
            metadata={"effective_sample_count": len(ctx.price_series)},
        ),
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
            timeframe=ctx.timeframe,
            state=_macd_state(macd_val, signal_val),
            minimum_samples=34,
            input_basis="close",
            method="macd",
            metadata={
                "signal": _safe_float(signal_val),
                "hist": _safe_float(hist_val),
                "effective_sample_count": len(ctx.price_series),
            },
        ),
        CLASSIC_STAGE,
    )


def _task_vwap(ctx: FeatureExecutionContext) -> None:
    if not supports_session_vwap_timeframe(ctx.timeframe):
        ctx.add_output(
            "VWAP",
            _snapshot(
                "VWAP",
                None,
                timeframe=ctx.timeframe,
                state="UNAVAILABLE",
                minimum_samples=1,
                input_basis="hlc3_volume",
                method="session_vwap",
                quality_flags=("REQUIRES_INTRADAY_SESSION_BARS",),
                metadata={"reason": "requires_intraday_session_bars"},
            ),
            CLASSIC_STAGE,
        )
        return

    if ctx.volume_series.empty:
        ctx.add_output(
            "VWAP",
            _snapshot(
                "VWAP",
                None,
                timeframe=ctx.timeframe,
                state="UNAVAILABLE",
                minimum_samples=1,
                input_basis="hlc3_volume",
                method="session_vwap",
                quality_flags=("MISSING_VOLUME",),
                metadata={"reason": "missing_volume"},
            ),
            CLASSIC_STAGE,
        )
        return

    if ctx.high_series.empty or ctx.low_series.empty:
        ctx.add_output(
            "VWAP",
            _snapshot(
                "VWAP",
                None,
                timeframe=ctx.timeframe,
                state="UNAVAILABLE",
                minimum_samples=1,
                input_basis="hlc3_volume",
                method="session_vwap",
                quality_flags=("MISSING_HIGH_LOW",),
                metadata={"reason": "missing_high_low"},
            ),
            CLASSIC_STAGE,
        )
        return

    vwap_series = compute_vwap(
        ctx.high_series,
        ctx.low_series,
        ctx.price_series,
        ctx.volume_series,
    )
    vwap_val = _latest_value(vwap_series)
    ctx.add_output(
        "VWAP",
        _snapshot(
            "VWAP",
            vwap_val,
            timeframe=ctx.timeframe,
            state=_compare_state(ctx.latest_price, vwap_val),
            minimum_samples=1,
            input_basis="hlc3_volume",
            method="session_vwap",
            metadata={"effective_sample_count": len(vwap_series)},
        ),
        CLASSIC_STAGE,
    )


def _task_mfi_14(ctx: FeatureExecutionContext) -> None:
    if ctx.volume_series.empty:
        ctx.add_output(
            "MFI_14",
            _snapshot(
                "MFI_14",
                None,
                timeframe=ctx.timeframe,
                state="UNAVAILABLE",
                minimum_samples=14,
                input_basis="close_volume",
                method="mfi_14",
                quality_flags=("MISSING_VOLUME",),
                metadata={"reason": "missing_volume"},
            ),
            CLASSIC_STAGE,
        )
        return

    mfi_series = compute_mfi(ctx.price_series, ctx.volume_series, window=14)
    mfi_val = _latest_value(mfi_series)
    ctx.add_output(
        "MFI_14",
        _snapshot(
            "MFI_14",
            mfi_val,
            timeframe=ctx.timeframe,
            state=_momentum_state(mfi_val),
            minimum_samples=14,
            input_basis="close_volume",
            method="mfi_14",
            metadata={"effective_sample_count": len(ctx.price_series)},
        ),
        CLASSIC_STAGE,
    )


def _task_atr_14(ctx: FeatureExecutionContext) -> None:
    if ctx.high_series.empty or ctx.low_series.empty:
        ctx.add_output(
            "ATR_14",
            _snapshot(
                "ATR_14",
                None,
                timeframe=ctx.timeframe,
                state="UNAVAILABLE",
                minimum_samples=14,
                input_basis="high_low_close",
                method="atr_14",
                quality_flags=("MISSING_HIGH_LOW",),
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
            timeframe=ctx.timeframe,
            state="UNAVAILABLE" if atr_series is None else None,
            minimum_samples=14,
            input_basis="high_low_close",
            method="atr_14",
            quality_flags=("ATR_EMPTY",) if atr_series is None else (),
            metadata={"effective_sample_count": len(ctx.price_series)},
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
                timeframe=ctx.timeframe,
                state="UNAVAILABLE",
                minimum_samples=14,
                input_basis="high_low_close",
                method="adx_14",
                quality_flags=("MISSING_HIGH_LOW",),
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
        _snapshot(
            "ADX_14",
            adx_val,
            timeframe=ctx.timeframe,
            state=_adx_state(adx_val),
            minimum_samples=14,
            input_basis="high_low_close",
            method="adx_14",
            metadata={"effective_sample_count": len(ctx.price_series)},
        ),
        CLASSIC_STAGE,
    )


def _task_atrp_14(ctx: FeatureExecutionContext) -> None:
    if ctx.high_series.empty or ctx.low_series.empty:
        ctx.add_output(
            "ATRP_14",
            _snapshot(
                "ATRP_14",
                None,
                timeframe=ctx.timeframe,
                state="UNAVAILABLE",
                minimum_samples=14,
                input_basis="high_low_close",
                method="atrp_14",
                quality_flags=("MISSING_HIGH_LOW",),
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
        _snapshot(
            "ATRP_14",
            atrp_val,
            timeframe=ctx.timeframe,
            state=_atrp_state(atrp_val),
            minimum_samples=14,
            input_basis="high_low_close",
            method="atrp_14",
            metadata={"effective_sample_count": len(ctx.price_series)},
        ),
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
            timeframe=ctx.timeframe,
            state=_bandwidth_state(bandwidth_val),
            minimum_samples=20,
            input_basis="close",
            method="bb_bandwidth_20",
            metadata={"effective_sample_count": len(ctx.price_series)},
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
        _snapshot(
            "FD_Z_SCORE",
            z_score_latest,
            timeframe=ctx.timeframe,
            state=_zscore_state(z_score_latest),
            minimum_samples=300,
            input_basis="fracdiff_close",
            method="fd_z_score",
            metadata={"effective_sample_count": len(fd_series)},
        ),
        QUANT_STAGE,
    )
    ctx.add_output(
        "FD_OPTIMAL_D",
        _snapshot(
            "FD_OPTIMAL_D",
            optimal_d,
            timeframe=ctx.timeframe,
            minimum_samples=300,
            input_basis="fracdiff_close",
            method="fd_optimal_d",
            metadata={"effective_sample_count": len(fd_series)},
        ),
        QUANT_STAGE,
    )
    ctx.add_output(
        "FD_ADF_STAT",
        _snapshot(
            "FD_ADF_STAT",
            adf_stat,
            timeframe=ctx.timeframe,
            minimum_samples=300,
            input_basis="fracdiff_close",
            method="fd_adf_stat",
            metadata={"effective_sample_count": len(fd_series)},
        ),
        QUANT_STAGE,
    )
    ctx.add_output(
        "FD_ADF_PVALUE",
        _snapshot(
            "FD_ADF_PVALUE",
            adf_pvalue,
            timeframe=ctx.timeframe,
            minimum_samples=300,
            input_basis="fracdiff_close",
            method="fd_adf_pvalue",
            metadata={"effective_sample_count": len(fd_series)},
        ),
        QUANT_STAGE,
    )
    ctx.add_output(
        "FD_STAT_STRENGTH",
        _snapshot(
            "FD_STAT_STRENGTH",
            stat_strength.get("value"),
            timeframe=ctx.timeframe,
            minimum_samples=300,
            input_basis="fracdiff_close",
            method="fd_stat_strength",
            metadata={"effective_sample_count": len(fd_series)},
        ),
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
            timeframe=ctx.timeframe,
            state=str(bollinger.get("state") or "INSIDE"),
            minimum_samples=300,
            input_basis="fracdiff_close",
            method="fd_bollinger_bw",
            metadata={
                "upper": _safe_float(bollinger.get("upper")),
                "lower": _safe_float(bollinger.get("lower")),
                "effective_sample_count": len(fd_series),
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
            timeframe=ctx.timeframe,
            state=str(obv_data.get("state") or "NEUTRAL"),
            minimum_samples=300,
            input_basis="fracdiff_close_volume",
            method="fd_obv_z",
            metadata={
                "optimal_d": _safe_float(obv_data.get("optimal_d")),
                "effective_sample_count": len(fd_series),
            },
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
    timeframe: TimeframeCode,
    state: str | None = None,
    minimum_samples: int | None = None,
    input_basis: str | None = None,
    method: str | None = None,
    quality_flags: tuple[str, ...] = (),
    metadata: dict[str, float | int | str | bool | None] | None = None,
) -> IndicatorSnapshot:
    payload = metadata or {}
    effective_sample_count = payload.get("effective_sample_count")
    effective_count = (
        effective_sample_count if isinstance(effective_sample_count, int) else None
    )
    value_num = _safe_float(value)
    return IndicatorSnapshot(
        name=name,
        value=value_num,
        state=state,
        provenance=IndicatorProvenance(
            method=method or name.lower(),
            input_basis=input_basis,
            source_timeframe=timeframe,
            calculation_version=FEATURE_CALCULATION_VERSION,
        ),
        quality=IndicatorQuality(
            effective_sample_count=effective_count,
            minimum_samples=minimum_samples,
            warmup_status=_warmup_status(
                effective_sample_count=effective_count,
                minimum_samples=minimum_samples,
                value=value_num,
                quality_flags=quality_flags,
            ),
            fidelity=_quality_fidelity(
                effective_sample_count=effective_count,
                minimum_samples=minimum_samples,
                value=value_num,
                quality_flags=quality_flags,
            ),
            quality_flags=quality_flags,
        ),
        metadata=payload,
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
) -> FeatureSummary:
    classic_total = sum(len(frame.classic_indicators) for frame in frames.values())
    quant_total = sum(len(frame.quant_features) for frame in frames.values())
    ready_timeframes: list[TimeframeCode] = []
    degraded_timeframes: list[TimeframeCode] = []
    regime_inputs_ready_timeframes: list[TimeframeCode] = []
    unavailable_indicator_count = 0

    for timeframe, frame in frames.items():
        all_indicators = {**frame.classic_indicators, **frame.quant_features}
        timeframe_degraded = False
        for indicator in all_indicators.values():
            if indicator.value is None:
                unavailable_indicator_count += 1
                timeframe_degraded = True
                continue
            quality = indicator.quality
            if quality is not None and quality.warmup_status not in {None, "READY"}:
                timeframe_degraded = True
        if timeframe_degraded:
            degraded_timeframes.append(timeframe)
        else:
            ready_timeframes.append(timeframe)
        if all(
            (
                signal in frame.classic_indicators
                and frame.classic_indicators[signal].value is not None
            )
            for signal in _REGIME_INPUT_SIGNALS
        ):
            regime_inputs_ready_timeframes.append(timeframe)

    overall_quality = "high"
    if unavailable_indicator_count > 0:
        overall_quality = "medium" if ready_timeframes else "low"
    if not frames:
        overall_quality = "low"

    return FeatureSummary(
        classic_count=classic_total,
        quant_count=quant_total,
        timeframe_count=len(frames),
        ready_timeframes=tuple(ready_timeframes),
        degraded_timeframes=tuple(degraded_timeframes),
        regime_inputs_ready_timeframes=tuple(regime_inputs_ready_timeframes),
        unavailable_indicator_count=unavailable_indicator_count,
        overall_quality=overall_quality,
    )


def _ensure_snapshot_contract(
    ctx: FeatureExecutionContext,
    snapshot: IndicatorSnapshot,
) -> IndicatorSnapshot:
    if snapshot.provenance is not None and snapshot.quality is not None:
        return snapshot
    method, input_basis, minimum_samples = _indicator_contract_defaults(snapshot.name)
    quality_flags = _extract_quality_flags(snapshot.metadata)
    return IndicatorSnapshot(
        name=snapshot.name,
        value=snapshot.value,
        state=snapshot.state,
        provenance=snapshot.provenance
        or IndicatorProvenance(
            method=method,
            input_basis=input_basis,
            source_timeframe=ctx.timeframe,
            calculation_version=FEATURE_CALCULATION_VERSION,
        ),
        quality=snapshot.quality
        or IndicatorQuality(
            effective_sample_count=len(ctx.price_series),
            minimum_samples=minimum_samples,
            warmup_status=_warmup_status(
                effective_sample_count=len(ctx.price_series),
                minimum_samples=minimum_samples,
                value=snapshot.value,
                quality_flags=quality_flags,
            ),
            fidelity=_quality_fidelity(
                effective_sample_count=len(ctx.price_series),
                minimum_samples=minimum_samples,
                value=snapshot.value,
                quality_flags=quality_flags,
            ),
            quality_flags=quality_flags,
        ),
        metadata=snapshot.metadata,
    )


def _indicator_contract_defaults(name: str) -> tuple[str, str | None, int | None]:
    if name in {"SMA_20", "EMA_20", "BB_BANDWIDTH_20"}:
        return name.lower(), "close", 20
    if name in {"RSI_14", "MFI_14", "ATR_14", "ATRP_14", "ADX_14"}:
        input_basis = "close"
        if name in {"ATR_14", "ATRP_14", "ADX_14"}:
            input_basis = "high_low_close"
        return name.lower(), input_basis, 14
    if name == "MACD":
        return "macd", "close", 34
    if name == "VWAP":
        return "session_vwap", "hlc3_volume", 1
    if name.startswith("FD_"):
        input_basis = "fracdiff_close"
        if name == "FD_OBV_Z":
            input_basis = "fracdiff_close_volume"
        return name.lower(), input_basis, 300
    return name.lower(), "close", None


def _extract_quality_flags(
    metadata: dict[str, float | int | str | bool | None],
) -> tuple[str, ...]:
    reason = metadata.get("reason")
    if isinstance(reason, str) and reason:
        return (reason.upper(),)
    return ()


def _warmup_status(
    *,
    effective_sample_count: int | None,
    minimum_samples: int | None,
    value: float | None,
    quality_flags: tuple[str, ...],
) -> str | None:
    if value is None:
        return "UNAVAILABLE"
    if (
        effective_sample_count is not None
        and minimum_samples is not None
        and effective_sample_count < minimum_samples
    ):
        return "INSUFFICIENT_HISTORY"
    if quality_flags:
        return "DEGRADED"
    return "READY"


def _quality_fidelity(
    *,
    effective_sample_count: int | None,
    minimum_samples: int | None,
    value: float | None,
    quality_flags: tuple[str, ...],
) -> str | None:
    if value is None:
        return "low"
    if (
        effective_sample_count is not None
        and minimum_samples is not None
        and effective_sample_count < minimum_samples
    ):
        return "low"
    if quality_flags:
        return "medium"
    return "high"
