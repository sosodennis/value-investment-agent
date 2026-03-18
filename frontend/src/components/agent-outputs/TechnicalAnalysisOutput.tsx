import React, { useState, useMemo, memo, useEffect, useRef } from 'react';
import { AgentStatus, ArtifactReference } from '@/types/agents';
import {
    Activity,
    TrendingUp,
    TrendingDown,
    BrainCircuit,
    LineChart,
    Layers,
    ChevronDown,
    ChevronUp,
    Zap,
    AlertTriangle,
    Bell,
    Sparkles
} from 'lucide-react';
import {
    parseTechnicalArtifact,
    parseTechnicalChartData,
    parseTechnicalFeaturePackArtifact,
    parseTechnicalPatternPackArtifact,
    parseTechnicalAlertsArtifact,
    parseTechnicalFusionReportArtifact,
    parseTechnicalDirectionScorecardArtifact,
    parseTechnicalVerificationReportArtifact,
    parseTechnicalIndicatorSeriesArtifact,
    parseTechnicalTimeseriesBundleArtifact,
} from '@/types/agents/artifact-parsers';
import {
    AlertSeverity,
    RiskLevel,
    TechnicalAlertsArtifact,
    TechnicalChartData,
    TechnicalConfidenceCalibration,
    TechnicalFeaturePack,
    TechnicalFusionReport,
    TechnicalDirectionScorecard,
    TechnicalScorecardContribution,
    TechnicalVerificationReport,
    TechnicalPatternPack,
    TechnicalIndicatorSeriesArtifact,
    TechnicalTimeseriesBundle
} from '@/types/agents/technical';
import { useArtifact } from '../../hooks/useArtifact';
import { AgentLoadingState } from './AgentLoadingState';
import { TechnicalPreview, isRecord } from '@/types/preview';
import {
    TechnicalCandlestickChart,
    CandlestickDatum,
    VolumeDatum,
    OverlayLineSeries
} from '@/components/charts/TechnicalCandlestickChart';
import {
    TechnicalIndicatorChart,
    IndicatorLineSeries,
    IndicatorHistogramSeries,
    IndicatorPriceLine
} from '@/components/charts/TechnicalIndicatorChart';
import { useCrosshairSync } from '@/components/charts/useCrosshairSync';
import {
    buildMomentumSummaryLine,
    describeIndicatorHighlight,
    getMarketStatusDescriptor,
    resolveFdDescriptor,
    resolveMacdTone,
    resolveRsiDescriptor,
    type IndicatorTone,
} from './technical-wording';

interface TechnicalAnalysisOutputProps {
    reference: ArtifactReference | null;
    previewData: TechnicalPreview | null;
    status: AgentStatus;
}

const PRICE_TIMEFRAME_PREFERENCE = ['1d', '1wk', '1h'] as const;
const LARGE_ARTIFACT_CACHE_MS = 5 * 60 * 1000;
const ALERT_SEVERITY_ORDER: Record<AlertSeverity, number> = {
    critical: 0,
    warning: 1,
    info: 2,
};
const CHART_PANE_HEIGHTS = {
    price: 260,
    volume: 90,
    rsi: 100,
    macd: 110,
    fracdiff: 90,
} as const;

// --- 1. Semantic Helpers ---

const formatLabel = (value: string) =>
    value
        .split('_')
        .map((part) =>
            part ? `${part.charAt(0).toUpperCase()}${part.slice(1).toLowerCase()}` : ''
        )
        .join(' ')
        .trim();

const getDirectionIcon = (direction: string) => {
    const normalized = direction.toLowerCase();
    if (normalized.includes('bull') || normalized.includes('up')) return TrendingUp;
    if (normalized.includes('bear') || normalized.includes('down')) return TrendingDown;
    return Activity;
};

const getRiskTone = (risk: RiskLevel) => {
    switch (risk) {
        case RiskLevel.LOW:
            return {
                label: 'Low Risk',
                color: 'text-emerald-400',
                border: 'border-emerald-500/30',
                bg: 'bg-emerald-500/10'
            };
        case RiskLevel.MEDIUM:
            return {
                label: 'Medium Risk',
                color: 'text-amber-400',
                border: 'border-amber-500/30',
                bg: 'bg-amber-500/10'
            };
        case RiskLevel.CRITICAL:
        default:
            return {
                label: 'Critical Risk',
                color: 'text-rose-400',
                border: 'border-rose-500/30',
                bg: 'bg-rose-500/10'
            };
    }
};

const getAlertSeverityTone = (severity: AlertSeverity) => {
    switch (severity) {
        case 'critical':
            return {
                label: 'Critical',
                badge: 'bg-rose-500/20 border-rose-500/40 text-rose-200',
                text: 'text-rose-200',
            };
        case 'warning':
            return {
                label: 'Warning',
                badge: 'bg-amber-500/20 border-amber-500/40 text-amber-200',
                text: 'text-amber-200',
            };
        case 'info':
        default:
            return {
                label: 'Info',
                badge: 'bg-slate-500/20 border-slate-500/40 text-slate-200',
                text: 'text-slate-200',
            };
    }
};

const formatConfidence = (value?: number) => {
    if (value === undefined || Number.isNaN(value)) return 'N/A';
    const normalized = value <= 1 ? value * 100 : value;
    return `${normalized.toFixed(1)}%`;
};

type ConfidencePayload = {
    confidence?: number | null;
    confidence_raw?: number | null;
    confidence_calibrated?: number | null;
    confidence_calibration?: TechnicalConfidenceCalibration;
};

const resolveConfidenceValue = (payload?: ConfidencePayload | null): number | undefined => {
    if (!payload) return undefined;
    const calibrated = payload.confidence_calibrated ?? undefined;
    const primary = payload.confidence ?? undefined;
    const raw = payload.confidence_raw ?? undefined;
    if (typeof calibrated === 'number') return calibrated;
    if (typeof primary === 'number') return primary;
    if (typeof raw === 'number') return raw;
    return undefined;
};

const formatCalibrationSource = (source?: string | null) => {
    if (!source) return 'Unknown';
    if (source === 'env_path') return 'Custom';
    if (source === 'default_artifact') return 'Default';
    if (source === 'embedded_default') return 'Fallback';
    return formatLabel(source);
};

const buildCalibrationLabel = (calibration?: TechnicalConfidenceCalibration) => {
    if (!calibration) return 'Fusion Estimate';
    const applied = calibration.calibration_applied;
    const sourceLabel = formatCalibrationSource(calibration.mapping_source);
    if (applied === false) {
        return `Uncalibrated · ${sourceLabel}`;
    }
    return `Calibrated · ${sourceLabel}`;
};

const formatArtifactLabel = (value: string) =>
    formatLabel(value.replace(/_id$/i, ''));

const formatArtifactId = (value: string) =>
    value.length > 12 ? `${value.slice(0, 6)}...${value.slice(-4)}` : value;

const formatIndicatorValue = (value: number | null | undefined) => {
    if (value === null || value === undefined || Number.isNaN(value)) return 'n/a';
    return value.toFixed(3);
};

const formatContributionValue = (value: number | null | undefined) => {
    if (value === null || value === undefined || Number.isNaN(value)) return '0.00';
    const rounded = value.toFixed(2);
    return value > 0 ? `+${rounded}` : rounded;
};

const tonePalette: Record<
    IndicatorTone,
    { badge: string; value: string; spark: string; glow: string }
> = {
    positive: {
        badge: 'bg-emerald-500/20 border-emerald-500/40 text-emerald-200',
        value: 'text-emerald-200',
        spark: '#22c55e',
        glow: '[text-shadow:0_0_15px_rgba(34,197,94,0.5)]',
    },
    neutral: {
        badge: 'bg-slate-500/20 border-slate-500/40 text-slate-200',
        value: 'text-slate-100',
        spark: '#94a3b8',
        glow: '[text-shadow:0_0_15px_rgba(148,163,184,0.5)]',
    },
    warning: {
        badge: 'bg-amber-500/20 border-amber-500/40 text-amber-200',
        value: 'text-amber-200',
        spark: '#f59e0b',
        glow: '[text-shadow:0_0_15px_rgba(245,158,11,0.5)]',
    },
    danger: {
        badge: 'bg-rose-500/20 border-rose-500/40 text-rose-200',
        value: 'text-rose-200',
        spark: '#f43f5e',
        glow: '[text-shadow:0_0_15px_rgba(244,63,94,0.5)]',
    },
};

const buildSparklinePoints = (values: number[], width = 120, height = 32) => {
    if (values.length < 2) return null;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    return values
        .map((value, index) => {
            const x = (index / (values.length - 1)) * width;
            const y = height - ((value - min) / range) * height;
            return `${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(' ');
};

const formatPrice = (value: number) => value.toFixed(2);
const formatVolume = (value: number | null | undefined) => {
    if (value === null || value === undefined || Number.isNaN(value)) return 'n/a';
    return new Intl.NumberFormat().format(value);
};
const formatTooltipTimestamp = (timestamp: number, includeTime: boolean) => {
    const date = new Date(timestamp * 1000);
    if (includeTime) {
        return date.toLocaleString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    }
    return date.toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
    });
};
const toEpochSeconds = (value: string) =>
    Math.floor(new Date(value).getTime() / 1000);
const buildIndicatorSeries = (series?: Record<string, number | null>) => {
    const entries = Object.entries(series ?? {})
        .map(([timestamp, value]) => ({
            time: toEpochSeconds(timestamp),
            value,
        }))
        .filter(
            (point): point is { time: number; value: number } =>
                typeof point.value === 'number' &&
                Number.isFinite(point.value) &&
                Number.isFinite(point.time)
        )
        .sort((a, b) => a.time - b.time)
        .map((point) => ({
            time: point.time as CandlestickDatum['time'],
            value: point.value,
        }));
    return entries;
};

const alignLineSeriesToTimes = (
    series: { time: CandlestickDatum['time']; value: number }[],
    times: CandlestickDatum['time'][]
) => {
    if (times.length === 0) return series;
    const map = new Map(series.map((point) => [point.time, point.value]));
    return times.map((time) => {
        const value = map.get(time);
        if (value === undefined) {
            return { time };
        }
        return { time, value };
    });
};

const alignHistogramSeriesToTimes = (
    series: { time: CandlestickDatum['time']; value: number; color?: string }[],
    times: CandlestickDatum['time'][]
) => {
    if (times.length === 0) return series;
    const map = new Map(series.map((point) => [point.time, point]));
    return times.map((time) => {
        const point = map.get(time);
        if (!point) {
            return { time };
        }
        return { time, value: point.value, color: point.color };
    });
};

type EpochTime = CandlestickDatum['time'];

const buildSeriesIndex = <V,>(series: { time: EpochTime; value: V }[]) => {
    const map = new Map<EpochTime, V>();
    const times: EpochTime[] = [];
    series.forEach((point) => {
        map.set(point.time, point.value);
        times.push(point.time);
    });
    times.sort((a, b) => a - b);
    return { times, map };
};

const buildCandleIndex = (series: CandlestickDatum[]) => {
    const map = new Map<EpochTime, CandlestickDatum>();
    const times: EpochTime[] = [];
    series.forEach((point) => {
        map.set(point.time, point);
        times.push(point.time);
    });
    times.sort((a, b) => a - b);
    return { times, map };
};

const findNearestTime = (times: EpochTime[], target: EpochTime): EpochTime | null => {
    if (times.length === 0) return null;
    const first = times[0];
    const last = times[times.length - 1];
    if (target <= first) return first;
    if (target >= last) return last;
    let low = 0;
    let high = times.length - 1;
    while (low <= high) {
        const mid = Math.floor((low + high) / 2);
        const value = times[mid];
        if (value === target) return value;
        if (value < target) {
            low = mid + 1;
        } else {
            high = mid - 1;
        }
    }
    const left = times[Math.max(0, high)];
    const right = times[Math.min(times.length - 1, low)];
    return target - left <= right - target ? left : right;
};

const resolveNearestValue = <V,>(
    index: { times: EpochTime[]; map: Map<EpochTime, V> },
    target: EpochTime
) => {
    const nearest = findNearestTime(index.times, target);
    if (nearest === null) return { time: null, value: null as V | null };
    return { time: nearest, value: index.map.get(nearest) ?? null };
};

const renderIndicatorHighlights = (indicators: TechnicalFeaturePack['timeframes'][string]['classic_indicators'][string][]) => {
    if (indicators.length === 0) {
        return <span className="text-xs text-slate-500">No indicators available.</span>;
    }
    return (
        <div className="flex flex-wrap gap-2">
            {indicators.map((indicator) => {
                const descriptor = describeIndicatorHighlight(
                    indicator.name,
                    indicator.state
                );
                return (
                    <span
                        key={indicator.name}
                        className="px-2.5 py-1 bg-slate-900/60 border border-slate-800 rounded-full text-[10px] font-bold text-slate-200 uppercase tracking-wide"
                    >
                        {descriptor.displayName}: {formatIndicatorValue(indicator.value)}
                        {descriptor.stateLabel ? ` · ${descriptor.stateLabel}` : ''}
                    </span>
                );
            })}
        </div>
    );
};

const renderScorecardContributions = (
    items: TechnicalScorecardContribution[]
) => {
    if (items.length === 0) {
        return <div className="text-[10px] text-slate-500">No contributions.</div>;
    }
    return (
        <div className="space-y-2">
            {items.map((item, idx) => {
                const valueText =
                    item.value === null || item.value === undefined
                        ? null
                        : formatIndicatorValue(item.value);
                const stateText = item.state ? formatLabel(item.state) : 'Neutral';
                const contributionTone =
                    item.contribution > 0
                        ? 'text-emerald-200'
                        : item.contribution < 0
                            ? 'text-rose-200'
                            : 'text-slate-400';
                return (
                    <div
                        key={`${item.name}-${idx}`}
                        className="flex items-center justify-between gap-3 text-[11px]"
                    >
                        <div>
                            <div className="text-slate-200 font-semibold">
                                {formatLabel(item.name)}
                            </div>
                            <div className="text-[10px] text-slate-500">
                                {stateText}
                                {valueText ? ` · ${valueText}` : ''}
                                {item.notes ? ` · ${item.notes}` : ''}
                            </div>
                        </div>
                        <div className={`font-mono font-semibold ${contributionTone}`}>
                            {formatContributionValue(item.contribution)}
                        </div>
                    </div>
                );
            })}
        </div>
    );
};

const MarketStatusBadge = ({ zScore }: { zScore: number }) => {
    const descriptor = getMarketStatusDescriptor(zScore);
    const toneClassMap: Record<
        IndicatorTone,
        { accentText: string; badge: string; iconTone: string }
    > = {
        positive: {
            accentText: 'text-emerald-300',
            badge: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-200',
            iconTone: 'text-emerald-300',
        },
        neutral: {
            accentText: 'text-slate-200',
            badge: 'bg-slate-900/60 border-slate-800 text-slate-300',
            iconTone: 'text-slate-400',
        },
        warning: {
            accentText: 'text-amber-300',
            badge: 'bg-amber-500/10 border-amber-500/30 text-amber-200',
            iconTone: 'text-amber-300',
        },
        danger: {
            accentText: 'text-rose-300',
            badge: 'bg-rose-500/10 border-rose-500/30 text-rose-200',
            iconTone: 'text-rose-300',
        },
    };
    const iconMap = {
        activity: Activity,
        alert: AlertTriangle,
        zap: Zap,
        up: TrendingUp,
        down: TrendingDown,
    } as const;
    const toneClasses = toneClassMap[descriptor.tone];
    const Icon = iconMap[descriptor.icon];

    return (
        <div className="bg-slate-950/50 border border-slate-800 rounded-xl p-4 flex items-center justify-between gap-6">
            <div className="flex items-center gap-4">
                <div className="p-2 rounded-lg bg-slate-900/60 border border-slate-800">
                    <Icon size={18} className={toneClasses.iconTone} />
                </div>
                <div>
                    <div className="text-[9px] font-black uppercase tracking-widest text-slate-500 mb-1">
                        Market Sentiment
                    </div>
                    <div className={`text-sm font-semibold ${toneClasses.accentText}`}>
                        {descriptor.status}
                    </div>
                </div>
            </div>
            <div className="text-right">
                <div className="text-[9px] font-black uppercase tracking-widest text-slate-500 mb-1">
                    {descriptor.readoutLabel}
                </div>
                <div className="text-xs text-slate-300">{descriptor.readout}</div>
                <span className={`inline-flex mt-2 px-2 py-0.5 rounded-full border text-[9px] font-bold uppercase tracking-wide ${toneClasses.badge}`}>
                    {Math.abs(zScore).toFixed(2)} z
                </span>
            </div>
        </div>
    );
};

// --- 2. Main Component ---

const TechnicalAnalysisOutputComponent: React.FC<TechnicalAnalysisOutputProps> = ({
    reference,
    previewData,
    status
}) => {
    const [indicatorLayoutMode, setIndicatorLayoutMode] = useState<'split' | 'combined' | 'summary'>('split');
    const [indicatorVisibility, setIndicatorVisibility] = useState({
        rsi: true,
        macd: true,
        fd: true,
    });
    const [activeIndicator, setActiveIndicator] = useState<'rsi' | 'macd'>('rsi');
    const [showFeaturePack, setShowFeaturePack] = useState(false);
    const [showPatternPack, setShowPatternPack] = useState(false);
    const [showAlerts, setShowAlerts] = useState(false);
    const [showFusionReport, setShowFusionReport] = useState(false);
    const [showVerificationReport, setShowVerificationReport] = useState(false);
    const [priceTimeframe, setPriceTimeframe] = useState<string | null>(null);
    const crosshairSync = useCrosshairSync();
    const chartStackRef = useRef<HTMLDivElement | null>(null);
    const [tooltipPosition, setTooltipPosition] = useState<{ x: number; y: number } | null>(null);
    const sectionHeaderTextClass = "text-[10px] font-black text-slate-400 uppercase tracking-widest";
    const sectionHeaderIconClass = "text-slate-400 opacity-70";

    const { data: reportData, isLoading: isArtifactLoading } = useArtifact(
        reference?.artifact_id,
        parseTechnicalArtifact,
        'technical_output.artifact',
        'ta_full_report'
    );

    const featurePackId = reportData?.artifact_refs.feature_pack_id ?? null;
    const {
        data: featurePackData,
        isLoading: isFeaturePackLoading,
        error: featurePackError,
    } = useArtifact<TechnicalFeaturePack>(
        showFeaturePack ? featurePackId : null,
        parseTechnicalFeaturePackArtifact,
        'technical_output.feature_pack',
        'ta_feature_pack'
    );

    const patternPackId = reportData?.artifact_refs.pattern_pack_id ?? null;
    const {
        data: patternPackData,
        isLoading: isPatternPackLoading,
        error: patternPackError,
    } = useArtifact<TechnicalPatternPack>(
        showPatternPack ? patternPackId : null,
        parseTechnicalPatternPackArtifact,
        'technical_output.pattern_pack',
        'ta_pattern_pack'
    );

    const alertsId = reportData?.artifact_refs.alerts_id ?? null;
    const {
        data: alertsData,
        isLoading: isAlertsLoading,
        error: alertsError,
    } = useArtifact<TechnicalAlertsArtifact>(
        showAlerts ? alertsId : null,
        parseTechnicalAlertsArtifact,
        'technical_output.alerts',
        'ta_alerts'
    );

    const fusionReportId = reportData?.artifact_refs.fusion_report_id ?? null;
    const {
        data: fusionReportData,
        isLoading: isFusionReportLoading,
        error: fusionReportError,
    } = useArtifact<TechnicalFusionReport>(
        showFusionReport ? fusionReportId : null,
        parseTechnicalFusionReportArtifact,
        'technical_output.fusion_report',
        'ta_fusion_report'
    );

    const directionScorecardId =
        reportData?.artifact_refs.direction_scorecard_id ?? null;
    const {
        data: directionScorecardData,
        isLoading: isDirectionScorecardLoading,
        error: directionScorecardError,
    } = useArtifact<TechnicalDirectionScorecard>(
        showFusionReport ? directionScorecardId : null,
        parseTechnicalDirectionScorecardArtifact,
        'technical_output.direction_scorecard',
        'ta_direction_scorecard'
    );

    const verificationReportId =
        reportData?.artifact_refs.verification_report_id ?? null;
    const {
        data: verificationReportData,
        isLoading: isVerificationReportLoading,
        error: verificationReportError,
    } = useArtifact<TechnicalVerificationReport>(
        showVerificationReport ? verificationReportId : null,
        parseTechnicalVerificationReportArtifact,
        'technical_output.verification_report',
        'ta_verification_report'
    );

    const chartDataId = reportData?.artifact_refs.chart_data_id ?? null;
    const {
        data: chartArtifact,
        error: chartError,
    } = useArtifact<TechnicalChartData>(
        chartDataId,
        parseTechnicalChartData,
        'technical_output.chart_data',
        'ta_chart_data'
    );

    const timeseriesBundleId = reportData?.artifact_refs.timeseries_bundle_id ?? null;
    const {
        data: timeseriesBundleData,
        error: timeseriesBundleError,
    } = useArtifact<TechnicalTimeseriesBundle>(
        timeseriesBundleId,
        parseTechnicalTimeseriesBundleArtifact,
        'technical_output.timeseries_bundle',
        'ta_timeseries_bundle',
        { dedupingInterval: LARGE_ARTIFACT_CACHE_MS }
    );

    const indicatorSeriesId = reportData?.artifact_refs.indicator_series_id ?? null;
    const {
        data: indicatorSeriesData,
        error: indicatorSeriesError,
    } = useArtifact<TechnicalIndicatorSeriesArtifact>(
        indicatorSeriesId,
        parseTechnicalIndicatorSeriesArtifact,
        'technical_output.indicator_series',
        'ta_indicator_series',
        { dedupingInterval: LARGE_ARTIFACT_CACHE_MS }
    );

    // Data Processing & Outlier Filtering
    const chartData = useMemo(() => {
        if (!chartArtifact?.z_score_series) return [];

        return Object.entries(chartArtifact.z_score_series)
            .filter(([, value]) => {
                if (typeof value !== 'number' || Math.abs(value) < 0.0001) return false;
                return true;
            })
            .map(([date, value]) => {
                const val = typeof value === 'number' ? value : 0;
                let displayValue = val;
                if (val > 10) displayValue = 10;
                if (val < -10) displayValue = -10;

                return {
                    date: new Date(date).toLocaleDateString(undefined, { month: 'numeric', day: 'numeric' }),
                    value: displayValue,
                    originalValue: val,
                    timestamp: new Date(date).getTime()
                };
            })
            .sort((a, b) => a.timestamp - b.timestamp);
    }, [chartArtifact]);

    const availableTimeseriesFrames = useMemo(() => {
        if (!timeseriesBundleData) return [];
        const frames = Object.keys(timeseriesBundleData.frames);
        return frames.sort((a, b) => {
            const indexA = PRICE_TIMEFRAME_PREFERENCE.indexOf(a as (typeof PRICE_TIMEFRAME_PREFERENCE)[number]);
            const indexB = PRICE_TIMEFRAME_PREFERENCE.indexOf(b as (typeof PRICE_TIMEFRAME_PREFERENCE)[number]);
            const normalizedA = indexA === -1 ? Number.MAX_SAFE_INTEGER : indexA;
            const normalizedB = indexB === -1 ? Number.MAX_SAFE_INTEGER : indexB;
            if (normalizedA !== normalizedB) return normalizedA - normalizedB;
            return a.localeCompare(b);
        });
    }, [timeseriesBundleData]);

    const preferredTimeseriesFrame = useMemo(() => {
        if (availableTimeseriesFrames.length === 0) return null;
        const preferred =
            availableTimeseriesFrames.find((frame) =>
                PRICE_TIMEFRAME_PREFERENCE.includes(frame as (typeof PRICE_TIMEFRAME_PREFERENCE)[number])
            ) ?? availableTimeseriesFrames[0];
        return preferred ?? null;
    }, [availableTimeseriesFrames]);

    useEffect(() => {
        if (!preferredTimeseriesFrame) return;
        setPriceTimeframe((prev) => {
            if (prev && availableTimeseriesFrames.includes(prev)) return prev;
            return preferredTimeseriesFrame;
        });
    }, [preferredTimeseriesFrame, availableTimeseriesFrames]);

    const selectedTimeseriesFrame = priceTimeframe && timeseriesBundleData
        ? timeseriesBundleData.frames[priceTimeframe]
        : null;

    const { candlestickSeries, volumeSeries } = useMemo(() => {
        if (!selectedTimeseriesFrame) {
            return { candlestickSeries: [], volumeSeries: [] };
        }
        const candles: CandlestickDatum[] = [];
        const volumes: VolumeDatum[] = [];
        const closeSeries = selectedTimeseriesFrame.close_series ?? {};
        const openSeries = selectedTimeseriesFrame.open_series ?? {};
        const highSeries = selectedTimeseriesFrame.high_series ?? {};
        const lowSeries = selectedTimeseriesFrame.low_series ?? {};
        const volumeSeriesRaw = selectedTimeseriesFrame.volume_series ?? {};

        Object.keys(closeSeries).forEach((timestamp) => {
            const open = openSeries[timestamp];
            const high = highSeries[timestamp];
            const low = lowSeries[timestamp];
            const close = closeSeries[timestamp];
            if (
                typeof open !== 'number' ||
                typeof high !== 'number' ||
                typeof low !== 'number' ||
                typeof close !== 'number'
            ) {
                return;
            }
            const time = toEpochSeconds(timestamp) as CandlestickDatum['time'];
            candles.push({ time, open, high, low, close });
            const volume = volumeSeriesRaw[timestamp];
            if (typeof volume === 'number') {
                volumes.push({
                    time,
                    value: volume,
                    color: close >= open ? 'rgba(34, 197, 94, 0.45)' : 'rgba(248, 113, 113, 0.45)',
                });
            }
        });

        candles.sort((a, b) => a.time - b.time);
        volumes.sort((a, b) => a.time - b.time);
        return { candlestickSeries: candles, volumeSeries: volumes };
    }, [selectedTimeseriesFrame]);

    const volumeHistogram = useMemo<IndicatorHistogramSeries[]>(
        () =>
            volumeSeries.length > 0
                ? [
                    {
                        id: 'Volume',
                        data: volumeSeries.map((point) => ({
                            time: point.time,
                            value: point.value,
                            color: point.color,
                        })),
                    },
                ]
                : [],
        [volumeSeries]
    );

    const timeseriesSummary = useMemo(() => {
        if (!timeseriesBundleData) return null;
        const frames = Object.values(timeseriesBundleData.frames);
        const frameCount = frames.length;
        const maxPoints = frames.reduce((acc, frame) => {
            const closePoints = Object.keys(frame.close_series ?? {}).length;
            const pricePoints = Object.keys(frame.price_series ?? {}).length;
            return Math.max(acc, closePoints, pricePoints);
        }, 0);
        return {
            frameCount,
            maxPoints,
            degradedReasons: timeseriesBundleData.degraded_reasons ?? [],
        };
    }, [timeseriesBundleData]);

    const timeseriesWindow = useMemo(() => {
        if (!selectedTimeseriesFrame) return null;
        return {
            start: new Date(selectedTimeseriesFrame.start).toLocaleDateString(),
            end: new Date(selectedTimeseriesFrame.end).toLocaleDateString(),
        };
    }, [selectedTimeseriesFrame]);
    const isIntradayTimeseries = priceTimeframe?.includes('h') ?? false;

    const indicatorTimeframe = useMemo(() => {
        if (!indicatorSeriesData) return null;
        if (priceTimeframe && indicatorSeriesData.timeframes[priceTimeframe]) {
            return priceTimeframe;
        }
        const frames = Object.keys(indicatorSeriesData.timeframes);
        return frames.length > 0 ? frames[0] : null;
    }, [indicatorSeriesData, priceTimeframe]);

    const indicatorFrame = useMemo(() => {
        if (!indicatorSeriesData || !indicatorTimeframe) return null;
        return indicatorSeriesData.timeframes[indicatorTimeframe] ?? null;
    }, [indicatorSeriesData, indicatorTimeframe]);

    const sma20Series = useMemo(() => buildIndicatorSeries(indicatorFrame?.series?.['SMA_20']), [indicatorFrame]);
    const ema20Series = useMemo(() => buildIndicatorSeries(indicatorFrame?.series?.['EMA_20']), [indicatorFrame]);
    const bbUpperSeries = useMemo(() => buildIndicatorSeries(indicatorFrame?.series?.['BB_UPPER']), [indicatorFrame]);
    const bbMiddleSeries = useMemo(() => buildIndicatorSeries(indicatorFrame?.series?.['BB_MIDDLE']), [indicatorFrame]);
    const bbLowerSeries = useMemo(() => buildIndicatorSeries(indicatorFrame?.series?.['BB_LOWER']), [indicatorFrame]);

    const priceOverlays = useMemo<OverlayLineSeries[]>(() => {
        const overlays: OverlayLineSeries[] = [];
        if (sma20Series.length > 0) {
            overlays.push({
                id: 'SMA 20',
                data: sma20Series,
                color: '#38bdf8',
                lineWidth: 2,
            });
        }
        if (ema20Series.length > 0) {
            overlays.push({
                id: 'EMA 20',
                data: ema20Series,
                color: '#f59e0b',
                lineWidth: 2,
            });
        }
        if (bbUpperSeries.length > 0) {
            overlays.push({
                id: 'BB Upper',
                data: bbUpperSeries,
                color: 'rgba(148, 163, 184, 0.6)',
                lineWidth: 1,
                lineStyle: 'dashed',
            });
        }
        if (bbMiddleSeries.length > 0) {
            overlays.push({
                id: 'BB Middle',
                data: bbMiddleSeries,
                color: 'rgba(148, 163, 184, 0.45)',
                lineWidth: 1,
                lineStyle: 'dashed',
            });
        }
        if (bbLowerSeries.length > 0) {
            overlays.push({
                id: 'BB Lower',
                data: bbLowerSeries,
                color: 'rgba(148, 163, 184, 0.6)',
                lineWidth: 1,
                lineStyle: 'dashed',
            });
        }
        return overlays;
    }, [bbLowerSeries, bbMiddleSeries, bbUpperSeries, ema20Series, sma20Series]);

    const rsiSeries = useMemo(() => buildIndicatorSeries(indicatorFrame?.series?.['RSI_14']), [indicatorFrame]);
    const macdSeries = useMemo(() => buildIndicatorSeries(indicatorFrame?.series?.['MACD']), [indicatorFrame]);
    const macdSignalSeries = useMemo(() => buildIndicatorSeries(indicatorFrame?.series?.['MACD_SIGNAL']), [indicatorFrame]);
    const macdHistSeries = useMemo(() => {
        const series = indicatorFrame?.series?.['MACD_HIST'] ?? null;
        return Object.entries(series ?? {})
            .map(([timestamp, value]) => ({
                time: toEpochSeconds(timestamp),
                value,
            }))
            .filter(
                (point): point is { time: number; value: number } =>
                    typeof point.value === 'number' &&
                    Number.isFinite(point.value) &&
                    Number.isFinite(point.time)
            )
            .sort((a, b) => a.time - b.time)
            .map((point) => ({
                time: point.time as CandlestickDatum['time'],
                value: point.value,
                color: point.value >= 0 ? 'rgba(34, 197, 94, 0.45)' : 'rgba(248, 113, 113, 0.45)',
            }));
    }, [indicatorFrame]);
    const fdSeries = useMemo(() => {
        if (indicatorFrame?.series?.['FD_ZSCORE']) {
            return buildIndicatorSeries(indicatorFrame.series['FD_ZSCORE']);
        }
        return buildIndicatorSeries(indicatorFrame?.series?.['FD']);
    }, [indicatorFrame]);

    const baseTimes = useMemo(() => {
        if (candlestickSeries.length > 0) {
            return candlestickSeries.map((point) => point.time);
        }
        if (rsiSeries.length > 0) return rsiSeries.map((point) => point.time);
        if (macdSeries.length > 0) return macdSeries.map((point) => point.time);
        if (macdSignalSeries.length > 0) return macdSignalSeries.map((point) => point.time);
        if (macdHistSeries.length > 0) return macdHistSeries.map((point) => point.time);
        if (fdSeries.length > 0) return fdSeries.map((point) => point.time);
        return [];
    }, [candlestickSeries, rsiSeries, macdSeries, macdSignalSeries, macdHistSeries, fdSeries]);

    const alignedRsiSeries = useMemo(
        () => alignLineSeriesToTimes(rsiSeries, baseTimes),
        [rsiSeries, baseTimes]
    );
    const alignedMacdSeries = useMemo(
        () => alignLineSeriesToTimes(macdSeries, baseTimes),
        [macdSeries, baseTimes]
    );
    const alignedMacdSignalSeries = useMemo(
        () => alignLineSeriesToTimes(macdSignalSeries, baseTimes),
        [macdSignalSeries, baseTimes]
    );
    const alignedMacdHistSeries = useMemo(
        () => alignHistogramSeriesToTimes(macdHistSeries, baseTimes),
        [macdHistSeries, baseTimes]
    );
    const alignedFdSeries = useMemo(
        () => alignLineSeriesToTimes(fdSeries, baseTimes),
        [fdSeries, baseTimes]
    );

    const indicatorAvailability = useMemo(
        () => ({
            rsi: rsiSeries.length > 0,
            macd: macdSeries.length > 0 || macdSignalSeries.length > 0 || macdHistSeries.length > 0,
            fd: fdSeries.length > 0,
        }),
        [rsiSeries, macdSeries, macdSignalSeries, macdHistSeries, fdSeries]
    );

    const visibleIndicators = useMemo(
        () => ({
            rsi: indicatorVisibility.rsi && indicatorAvailability.rsi,
            macd: indicatorVisibility.macd && indicatorAvailability.macd,
            fd: indicatorVisibility.fd && indicatorAvailability.fd,
        }),
        [indicatorAvailability, indicatorVisibility]
    );

    const classicVisibleIndicators = useMemo(
        () => ({
            rsi: visibleIndicators.rsi,
            macd: visibleIndicators.macd,
        }),
        [visibleIndicators]
    );
    const hasEvidenceIndicators =
        visibleIndicators.rsi || visibleIndicators.macd || visibleIndicators.fd;
    const classicIndicatorKeys: Array<'rsi' | 'macd'> = ['rsi', 'macd'];

    const bottomTimeScalePane = useMemo(() => {
        if (indicatorAvailability.fd) return 'fd';
        if (indicatorAvailability.macd) return 'macd';
        if (indicatorAvailability.rsi) return 'rsi';
        if (volumeHistogram.length > 0) return 'volume';
        return 'price';
    }, [indicatorAvailability, volumeHistogram.length]);

    useEffect(() => {
        const candidates = classicIndicatorKeys.filter((key) => classicVisibleIndicators[key]);
        if (candidates.length === 0) {
            return;
        }
        if (!candidates.includes(activeIndicator)) {
            setActiveIndicator(candidates[0]);
        }
    }, [activeIndicator, classicVisibleIndicators]);

    const latestRsi = rsiSeries.length > 0 ? rsiSeries[rsiSeries.length - 1].value : null;
    const latestMacd = macdSeries.length > 0 ? macdSeries[macdSeries.length - 1].value : null;
    const latestMacdSignal =
        macdSignalSeries.length > 0 ? macdSignalSeries[macdSignalSeries.length - 1].value : null;
    const latestFd = fdSeries.length > 0 ? fdSeries[fdSeries.length - 1].value : null;
    const momentumExtremes = reportData?.momentum_extremes;
    const momentumRsiValue =
        momentumExtremes && momentumExtremes.rsi_value !== undefined
            ? momentumExtremes.rsi_value
            : latestRsi;
    const momentumFdValue =
        momentumExtremes && momentumExtremes.fd_z_score !== undefined
            ? momentumExtremes.fd_z_score
            : latestFd;
    const momentumTimeframe =
        momentumExtremes?.timeframe ?? indicatorTimeframe ?? null;
    const hasMomentumExtremes =
        momentumExtremes !== undefined ||
        momentumRsiValue !== null ||
        momentumFdValue !== null;
    const toSparklineValues = (series: { value: number }[], count = 12) =>
        series
            .slice(-count)
            .map((point) => point.value)
            .filter((value) => Number.isFinite(value));

    const rsiSparkline = useMemo(
        () => buildSparklinePoints(toSparklineValues(rsiSeries)),
        [rsiSeries]
    );
    const macdSparkline = useMemo(
        () => buildSparklinePoints(toSparklineValues(macdSeries)),
        [macdSeries]
    );
    const fdSparkline = useMemo(
        () => buildSparklinePoints(toSparklineValues(fdSeries)),
        [fdSeries]
    );

    const momentumRsiDescriptor = useMemo(
        () =>
            resolveRsiDescriptor(
                momentumRsiValue ?? null,
                momentumExtremes?.rsi_bias
            ),
        [momentumExtremes?.rsi_bias, momentumRsiValue]
    );
    const macdTone = useMemo(
        () => resolveMacdTone(latestMacd, latestMacdSignal),
        [latestMacd, latestMacdSignal]
    );
    const momentumFdDescriptor = useMemo(
        () =>
            resolveFdDescriptor(
                momentumFdValue ?? null,
                momentumExtremes?.fd_label
            ),
        [momentumExtremes?.fd_label, momentumFdValue]
    );
    const momentumFdRiskHint =
        momentumExtremes && momentumExtremes.fd_risk_hint !== undefined
            ? formatLabel(momentumExtremes.fd_risk_hint ?? 'No Data')
            : null;
    const momentumSummary = useMemo(() => {
        if (!hasMomentumExtremes) return null;
        return buildMomentumSummaryLine({
            macd: visibleIndicators.macd ? macdTone : null,
            rsi: momentumRsiDescriptor,
            fd: momentumFdDescriptor,
            rsiValue: momentumRsiValue,
            fdValue: momentumFdValue,
        });
    }, [
        hasMomentumExtremes,
        macdTone,
        momentumFdDescriptor,
        momentumFdValue,
        momentumRsiDescriptor,
        momentumRsiValue,
        visibleIndicators.macd,
    ]);

    const rsiLines = useMemo<IndicatorLineSeries[]>(
        () => [
            {
                id: 'RSI 14',
                data: alignedRsiSeries,
                color: '#38bdf8',
                lineWidth: 2,
            },
        ],
        [alignedRsiSeries]
    );
    const macdLines = useMemo<IndicatorLineSeries[]>(
        () => [
            { id: 'MACD', data: alignedMacdSeries, color: '#fbbf24', lineWidth: 2 },
            { id: 'Signal', data: alignedMacdSignalSeries, color: '#22d3ee', lineWidth: 2 },
        ],
        [alignedMacdSeries, alignedMacdSignalSeries]
    );
    const macdHistogram = useMemo<IndicatorHistogramSeries[]>(
        () => [
            {
                id: 'Histogram',
                data: alignedMacdHistSeries,
                color: 'rgba(148, 163, 184, 0.35)',
            },
        ],
        [alignedMacdHistSeries]
    );
    const fdLines = useMemo<IndicatorLineSeries[]>(
        () => [
            {
                id: indicatorFrame?.series?.['FD_ZSCORE'] ? 'FD Z-Score' : 'FracDiff',
                data: alignedFdSeries,
                color: '#a855f7',
                lineWidth: 2,
            },
        ],
        [alignedFdSeries, indicatorFrame]
    );

    const candleIndex = useMemo(() => buildCandleIndex(candlestickSeries), [candlestickSeries]);
    const volumeIndex = useMemo(() => buildSeriesIndex(volumeSeries), [volumeSeries]);
    const rsiIndex = useMemo(() => buildSeriesIndex(rsiSeries), [rsiSeries]);
    const macdIndex = useMemo(() => buildSeriesIndex(macdSeries), [macdSeries]);
    const macdSignalIndex = useMemo(() => buildSeriesIndex(macdSignalSeries), [macdSignalSeries]);
    const macdHistIndex = useMemo(() => buildSeriesIndex(macdHistSeries), [macdHistSeries]);
    const fdIndex = useMemo(() => buildSeriesIndex(fdSeries), [fdSeries]);

    const tooltipPayload = useMemo(() => {
        if (!crosshairSync.crosshairTime) return null;
        const anchorTime = crosshairSync.crosshairTime as EpochTime;
        const candleMatch = resolveNearestValue(candleIndex, anchorTime);
        const volumeMatch = resolveNearestValue(volumeIndex, anchorTime);
        const rsiMatch = resolveNearestValue(rsiIndex, anchorTime);
        const macdMatch = resolveNearestValue(macdIndex, anchorTime);
        const macdSignalMatch = resolveNearestValue(macdSignalIndex, anchorTime);
        const macdHistMatch = resolveNearestValue(macdHistIndex, anchorTime);
        const fdMatch = resolveNearestValue(fdIndex, anchorTime);
        return {
            time: candleMatch.time ?? anchorTime,
            candle: candleMatch.value,
            volume: volumeMatch.value,
            rsi: rsiMatch.value,
            macd: macdMatch.value,
            macdSignal: macdSignalMatch.value,
            macdHist: macdHistMatch.value,
            fd: fdMatch.value,
        };
    }, [
        candleIndex,
        crosshairSync.crosshairTime,
        fdIndex,
        macdHistIndex,
        macdIndex,
        macdSignalIndex,
        rsiIndex,
        volumeIndex,
    ]);

    const rsiPriceLines = useMemo<IndicatorPriceLine[]>(
        () => [
            {
                price: 70,
                color: 'rgba(248, 113, 113, 0.55)',
                axisLabelColor: 'rgba(248, 113, 113, 0.4)',
                axisLabelTextColor: '#ffffff',
                title: 'Overbought',
                style: 'dashed',
            },
            {
                price: 30,
                color: 'rgba(34, 197, 94, 0.55)',
                axisLabelColor: 'rgba(34, 197, 94, 0.4)',
                axisLabelTextColor: '#ffffff',
                title: 'Oversold',
                style: 'dashed',
            },
        ],
        []
    );
    const macdPriceLines = useMemo<IndicatorPriceLine[]>(
        () => [
            {
                price: 0,
                color: 'rgba(148, 163, 184, 0.55)',
                axisLabelColor: 'rgba(148, 163, 184, 0.4)',
                axisLabelTextColor: '#0f172a',
                title: 'Zero',
                style: 'dashed',
            },
        ],
        []
    );
    const fdPriceLines = useMemo<IndicatorPriceLine[]>(
        () => [
            {
                price: 2,
                color: 'rgba(248, 113, 113, 0.55)',
                axisLabelColor: 'rgba(248, 113, 113, 0.4)',
                axisLabelTextColor: '#ffffff',
                title: '+2',
                style: 'dashed',
            },
            {
                price: -2,
                color: 'rgba(34, 197, 94, 0.55)',
                axisLabelColor: 'rgba(34, 197, 94, 0.4)',
                axisLabelTextColor: '#ffffff',
                title: '-2',
                style: 'dashed',
            },
        ],
        []
    );

    useEffect(() => {
        if (!crosshairSync.crosshairPoint || !chartStackRef.current) {
            setTooltipPosition(null);
            return;
        }
        const rect = chartStackRef.current.getBoundingClientRect();
        const anchorX = crosshairSync.crosshairPoint.x - rect.left;
        const anchorY = crosshairSync.crosshairPoint.y - rect.top;
        const TOOLTIP_WIDTH = 240;
        const TOOLTIP_HEIGHT = 190;
        const padding = 12;
        const maxX = Math.max(padding, rect.width - TOOLTIP_WIDTH - padding);
        const maxY = Math.max(padding, rect.height - TOOLTIP_HEIGHT - padding);
        setTooltipPosition({
            x: Math.min(Math.max(anchorX + padding, padding), maxX),
            y: Math.min(Math.max(anchorY + padding, padding), maxY),
        });
    }, [crosshairSync.crosshairPoint]);

    const classicIndicatorLayoutOptions = [
        { id: 'split', label: 'Split' },
        { id: 'combined', label: 'Combined' },
        { id: 'summary', label: 'Summary' },
    ] as const;

    const classicIndicatorToggleOptions = [
        { id: 'rsi', label: 'RSI' },
        { id: 'macd', label: 'MACD' },
    ] as const;
    const fracdiffIndicatorToggleOptions = [{ id: 'fd', label: 'FD' }] as const;

    const toggleIndicatorVisibility = (key: 'rsi' | 'macd' | 'fd') => {
        setIndicatorVisibility((prev) => ({ ...prev, [key]: !prev[key] }));
    };

    const classicVisibleIndicatorList = classicIndicatorToggleOptions.filter(
        (option) => classicVisibleIndicators[option.id]
    );
    const hasClassicIndicators = classicVisibleIndicatorList.length > 0;

    const mtfSummary = useMemo(() => {
        const timeframes = new Set<string>();
        if (timeseriesBundleData) {
            Object.keys(timeseriesBundleData.frames).forEach((frame) => timeframes.add(frame));
        }
        if (indicatorSeriesData) {
            Object.keys(indicatorSeriesData.timeframes).forEach((frame) => timeframes.add(frame));
        }
        if (timeframes.size === 0) return null;

        const entries = Array.from(timeframes).map((frameKey) => {
            const priceFrame = timeseriesBundleData?.frames[frameKey];
            const indicatorFrame = indicatorSeriesData?.timeframes[frameKey];
            const pricePoints = priceFrame
                ? Object.keys(priceFrame.close_series ?? {}).length
                : 0;
            const indicatorSeriesCount = indicatorFrame
                ? Object.keys(indicatorFrame.series).length
                : 0;
            const indicatorPoints = indicatorFrame
                ? Object.values(indicatorFrame.series).reduce((acc, series) => {
                    const count = Object.keys(series ?? {}).length;
                    return Math.max(acc, count);
                }, 0)
                : 0;
            const indicatorMeta = indicatorFrame?.metadata;
            const sourcePoints =
                indicatorMeta &&
                    isRecord(indicatorMeta) &&
                    typeof indicatorMeta.source_points === 'number'
                    ? indicatorMeta.source_points
                    : null;
            return {
                timeframe: frameKey,
                hasPrice: Boolean(priceFrame),
                hasIndicators: Boolean(indicatorFrame),
                pricePoints,
                indicatorSeriesCount,
                indicatorPoints,
                sourcePoints,
            };
        });

        return entries.sort((a, b) => {
            const indexA = PRICE_TIMEFRAME_PREFERENCE.indexOf(a.timeframe as (typeof PRICE_TIMEFRAME_PREFERENCE)[number]);
            const indexB = PRICE_TIMEFRAME_PREFERENCE.indexOf(b.timeframe as (typeof PRICE_TIMEFRAME_PREFERENCE)[number]);
            const normalizedA = indexA === -1 ? Number.MAX_SAFE_INTEGER : indexA;
            const normalizedB = indexB === -1 ? Number.MAX_SAFE_INTEGER : indexB;
            if (normalizedA !== normalizedB) return normalizedA - normalizedB;
            return a.timeframe.localeCompare(b.timeframe);
        });
    }, [timeseriesBundleData, indicatorSeriesData]);

    const featurePackSummary = useMemo(() => {
        if (!featurePackData) return null;
        const summaries = Object.entries(featurePackData.timeframes).map(
            ([frameKey, frame]) => {
                const classicEntries = Object.values(frame.classic_indicators);
                const quantEntries = Object.values(frame.quant_features);
                return {
                    timeframe: frameKey,
                    classicCount: classicEntries.length,
                    quantCount: quantEntries.length,
                    classicHighlights: classicEntries.slice(0, 3),
                    quantHighlights: quantEntries.slice(0, 3),
                };
            }
        );
        const classicTotal = summaries.reduce(
            (acc, entry) => acc + entry.classicCount,
            0
        );
        const quantTotal = summaries.reduce(
            (acc, entry) => acc + entry.quantCount,
            0
        );
        return {
            summaries,
            classicTotal,
            quantTotal,
        };
    }, [featurePackData]);

    const patternPackSummary = useMemo(() => {
        if (!patternPackData) return null;
        const summaries = Object.entries(patternPackData.timeframes).map(
            ([frameKey, frame]) => {
                const supportCount = frame.support_levels.length;
                const resistanceCount = frame.resistance_levels.length;
                const breakoutCount = frame.breakouts.length;
                const trendCount = frame.trendlines.length;
                const flagCount = frame.pattern_flags.length;
                return {
                    timeframe: frameKey,
                    supportCount,
                    resistanceCount,
                    breakoutCount,
                    trendCount,
                    flagCount,
                    supportLevels: frame.support_levels.slice(0, 3),
                    resistanceLevels: frame.resistance_levels.slice(0, 3),
                    breakoutFlags: frame.breakouts.slice(0, 3),
                    trendFlags: frame.trendlines.slice(0, 3),
                };
            }
        );
        const totalLevels = summaries.reduce(
            (acc, entry) => acc + entry.supportCount + entry.resistanceCount,
            0
        );
        const totalFlags = summaries.reduce(
            (acc, entry) => acc + entry.breakoutCount + entry.trendCount + entry.flagCount,
            0
        );
        return {
            summaries,
            totalLevels,
            totalFlags,
        };
    }, [patternPackData]);

    const alertsSummary = useMemo(() => {
        if (!alertsData) return null;
        const computedCounts = alertsData.alerts.reduce(
            (acc, alert) => {
                if (alert.severity in acc) {
                    acc[alert.severity as AlertSeverity] += 1;
                }
                return acc;
            },
            { critical: 0, warning: 0, info: 0 }
        );
        const summaryCounts = alertsData.summary?.severity_counts ?? {};
        const severityCounts = {
            ...computedCounts,
            ...Object.fromEntries(
                Object.entries(summaryCounts).filter(
                    ([, value]) => typeof value === 'number'
                )
            ),
        };
        const sortedAlerts = [...alertsData.alerts].sort((a, b) => {
            const severityOrder =
                ALERT_SEVERITY_ORDER[a.severity] - ALERT_SEVERITY_ORDER[b.severity];
            if (severityOrder !== 0) return severityOrder;
            const timeframeOrder = a.timeframe.localeCompare(b.timeframe);
            if (timeframeOrder !== 0) return timeframeOrder;
            return a.title.localeCompare(b.title);
        });
        return {
            total: alertsData.summary?.total ?? alertsData.alerts.length,
            severityCounts,
            generatedAt: alertsData.summary?.generated_at ?? null,
            alerts: sortedAlerts,
        };
    }, [alertsData]);

    const fusionReportSummary = useMemo(() => {
        if (!fusionReportData?.confluence_matrix) return null;
        const entries = Object.entries(fusionReportData.confluence_matrix).map(
            ([frameKey, row]) => {
                const classic = isRecord(row) && typeof row.classic === 'string' ? row.classic : 'n/a';
                const quant = isRecord(row) && typeof row.quant === 'string' ? row.quant : 'n/a';
                const pattern = isRecord(row) && typeof row.pattern === 'string' ? row.pattern : 'n/a';
                const classicScore =
                    isRecord(row) && typeof row.classic_score === 'number' ? row.classic_score : null;
                const quantScore =
                    isRecord(row) && typeof row.quant_score === 'number' ? row.quant_score : null;
                const patternScore =
                    isRecord(row) && typeof row.pattern_score === 'number' ? row.pattern_score : null;
                return {
                    timeframe: frameKey,
                    classic,
                    quant,
                    pattern,
                    classicScore,
                    quantScore,
                    patternScore,
                };
            }
        );
        return {
            entries,
            totalFrames: entries.length,
        };
    }, [fusionReportData]);

    const scorecardSummary = useMemo(() => {
        if (!directionScorecardData) return null;
        const priority = (frame: string) => {
            const idx = PRICE_TIMEFRAME_PREFERENCE.indexOf(
                frame as (typeof PRICE_TIMEFRAME_PREFERENCE)[number]
            );
            return idx === -1 ? 99 : idx;
        };
        const entries = Object.entries(directionScorecardData.timeframes)
            .map(([frameKey, frame]) => ({
                timeframe: frameKey,
                frame,
            }))
            .sort((a, b) => priority(a.timeframe) - priority(b.timeframe));
        return {
            entries,
            modelVersion: directionScorecardData.model_version ?? null,
            overallScore: directionScorecardData.overall_score,
            neutralThreshold: directionScorecardData.neutral_threshold,
        };
    }, [directionScorecardData]);

    const verificationSummary = useMemo(() => {
        if (!verificationReportData) return null;
        const gatesCount = verificationReportData.baseline_gates
            ? Object.keys(verificationReportData.baseline_gates).length
            : 0;
        const flagsCount = verificationReportData.robustness_flags?.length ?? 0;
        return {
            gatesCount,
            flagsCount,
        };
    }, [verificationReportData]);

    const chartStats = useMemo(() => {
        if (chartData.length === 0) return null;
        const values = chartData
            .map((entry) => entry.originalValue)
            .filter((v): v is number => typeof v === 'number' && !isNaN(v));
        if (values.length === 0) return null;
        const latest = chartData[chartData.length - 1].originalValue;
        const min = Math.min(...values);
        const max = Math.max(...values);
        const coverageDays = Math.max(
            0,
            Math.round(
                (chartData[chartData.length - 1].timestamp - chartData[0].timestamp) /
                86400000
            )
        );
        return {
            latest,
            min,
            max,
            count: chartData.length,
            coverageDays,
        };
    }, [chartData]);

    const isAlertsLoadingState =
        Boolean(alertsId) && isAlertsLoading && !alertsData;

    const indicatorSeriesSummary = useMemo(() => {
        if (!indicatorSeriesData) return null;
        const frames = Object.values(indicatorSeriesData.timeframes);
        const timeframeCount = frames.length;
        const seriesTotal = frames.reduce(
            (acc, frame) => acc + Object.keys(frame.series).length,
            0
        );
        const maxPoints = frames.reduce((acc, frame) => {
            const meta = frame.metadata;
            const points =
                meta && typeof meta.source_points === 'number' ? meta.source_points : 0;
            return Math.max(acc, points);
        }, 0);
        return {
            timeframeCount,
            seriesTotal,
            maxPoints,
            degradedReasons: indicatorSeriesData.degraded_reasons || [],
        };
    }, [indicatorSeriesData]);

    const hasData = !!reportData || !!previewData;

    if ((status !== 'done' && !hasData) || (!reportData && !previewData)) {
        return (
            <AgentLoadingState
                type="full"
                icon={Activity}
                title="Processing Statistical Framework..."
                description="Initializing Analysis Module and computing fractal differences."
                status={status}
                colorClass="text-cyan-400"
            />
        );
    }

    if (!reportData && previewData?.signal_display) {
        return (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-700">
                <header className="space-y-4">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/20 to-blue-600/20 border border-cyan-500/30 flex items-center justify-center shadow-inner">
                            <LineChart className="text-cyan-400" size={20} />
                        </div>
                        <div>
                            <h3 className="text-xl font-bold text-white tracking-tight">Technical Intelligence (Preview)</h3>
                            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                                <span className="text-cyan-400">{previewData?.ticker || 'UNKNOWN'}</span>
                            </div>
                        </div>
                    </div>
                </header>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="tech-card p-4 text-center group hover:bg-slate-900/40">
                        <div className="text-label mb-1 text-slate-600 group-hover:text-slate-400 transition-colors">Signal</div>
                        <div className="text-lg font-black text-white">{previewData.signal_display}</div>
                    </div>
                    <div className="tech-card p-4 text-center group hover:bg-slate-900/40">
                        <div className="text-label mb-1 text-slate-600 group-hover:text-slate-400 transition-colors">Price</div>
                        <div className="text-lg font-black text-white">{previewData.latest_price_display}</div>
                    </div>
                    <div className="tech-card p-4 text-center group hover:bg-slate-900/40">
                        <div className="text-label mb-1 text-slate-600 group-hover:text-slate-400 transition-colors">Z-Score</div>
                        <div className="text-lg font-black text-white">{previewData.z_score_display}</div>
                    </div>
                    <div className="tech-card p-4 text-center group hover:bg-slate-900/40">
                        <div className="text-label mb-1 text-slate-600 group-hover:text-slate-400 transition-colors">Opt. d</div>
                        <div className="text-lg font-black text-white">{previewData.optimal_d_display}</div>
                    </div>
                </div>

                <AgentLoadingState
                    type="block"
                    title="Loading Full Statistical Analysis..."
                    colorClass="text-cyan-400"
                />
            </div>
        );
    }

    if (!reportData) {
        return (
            <AgentLoadingState
                type="full"
                title="Loading Technical Report..."
                colorClass="text-cyan-400"
                status={status}
            />
        );
    }

    const DirectionIcon = getDirectionIcon(reportData.direction);
    const riskTone = getRiskTone(reportData.risk_level);
    const confidenceValue = resolveConfidenceValue(reportData);
    const confidenceDisplay = formatConfidence(confidenceValue);
    const confidenceLabel = buildCalibrationLabel(reportData.confidence_calibration);
    const fusionConfidenceValue = resolveConfidenceValue(fusionReportData);
    const fusionConfidenceDisplay = formatConfidence(fusionConfidenceValue);
    const fusionConfidenceLabel = buildCalibrationLabel(
        fusionReportData?.confidence_calibration
    );
    const fusionRawDisplay =
        fusionReportData?.confidence_raw !== undefined
            ? formatConfidence(fusionReportData.confidence_raw ?? undefined)
            : null;
    const degradedReasons = reportData.diagnostics?.degraded_reasons ?? [];
    const isDegraded = reportData.diagnostics?.is_degraded === true;
    const analystPerspective = reportData.analyst_perspective;
    const analystEvidence = analystPerspective?.top_evidence ?? [];
    const analystSignalExplainers = analystPerspective?.signal_explainers ?? [];
    const analystInvalidationLevel =
        typeof analystPerspective?.invalidation_level === 'number'
            ? analystPerspective.invalidation_level.toFixed(2)
            : null;
    const artifactEntries = Object.entries(reportData.artifact_refs).filter(
        (entry): entry is [string, string] =>
            typeof entry[1] === 'string' && entry[1].length > 0
    );

    return (
        <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-700">
            <header className="space-y-4">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/20 to-blue-600/20 border border-cyan-500/30 flex items-center justify-center shadow-inner">
                        <LineChart className="text-cyan-400" size={20} />
                    </div>
                    <div>
                        <h3 className="text-xl font-bold text-white tracking-tight">Technical Intelligence</h3>
                        <div className="flex flex-wrap items-center gap-2 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                            <span className="text-cyan-400">{reportData.ticker}</span>
                            <span className="opacity-30">|</span>
                            <span>{formatLabel(reportData.schema_version)}</span>
                            <span className="opacity-30">|</span>
                            <span>As of {reportData.as_of}</span>
                        </div>
                    </div>
                </div>
            </header>

            <section className="space-y-4">
                <div className="flex items-center gap-2">
                    <Activity size={14} className="text-cyan-400 opacity-70" />
                    <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">Overview</span>
                </div>

                <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="tech-card p-4 flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <div className="p-2 rounded-lg bg-white/5 backdrop-blur-md">
                                <DirectionIcon size={20} className="text-cyan-400" />
                            </div>
                            <div>
                                <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Direction</div>
                                <div className="text-lg font-black text-white">{formatLabel(reportData.direction)}</div>
                            </div>
                        </div>
                    </div>
                    <div className={`tech-card p-4 border ${riskTone.border} ${riskTone.bg}`}>
                        <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Risk Level</div>
                        <div className={`text-lg font-black ${riskTone.color}`}>{riskTone.label}</div>
                        {isDegraded && (
                            <div className="text-[9px] font-bold uppercase tracking-widest text-rose-300 mt-1">
                                Degraded Data Path
                            </div>
                        )}
                    </div>
                    <div className="tech-card p-4">
                        <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Confidence</div>
                        <div className="text-lg font-black text-white">{confidenceDisplay}</div>
                        <div className="text-[9px] text-slate-500 uppercase tracking-widest mt-1">{confidenceLabel}</div>
                    </div>
                </section>

                {momentumSummary && (
                    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                        <span className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-slate-500">
                            <Zap size={12} className="text-amber-300" />
                            Momentum & Extremes
                        </span>
                        {momentumTimeframe && (
                            <span className="text-[9px] text-slate-600 uppercase">
                                {momentumTimeframe.toUpperCase()}
                            </span>
                        )}
                        <span className="text-slate-300">{momentumSummary}</span>
                    </div>
                )}

                <section className="tech-card p-6 relative overflow-hidden group shadow-2xl bg-indigo-500/[0.03] border-indigo-500/20">
                    <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                        <BrainCircuit size={80} className="text-indigo-400" />
                    </div>
                    <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                        <div className="flex items-center gap-2">
                            <BrainCircuit size={18} className="text-indigo-400" />
                            <span className="text-xs font-black text-indigo-200 uppercase tracking-[0.2em]">Analyst Perspective</span>
                        </div>
                        {analystPerspective?.decision_posture && (
                            <span className="px-3 py-1 rounded-full border border-indigo-400/25 bg-indigo-500/10 text-[10px] font-black uppercase tracking-[0.18em] text-indigo-200">
                                {formatLabel(analystPerspective.decision_posture)}
                            </span>
                        )}
                    </div>
                    {analystPerspective ? (
                        <div className="space-y-5">
                            <div className="flex flex-wrap items-start justify-between gap-4">
                                <div className="space-y-2">
                                    <div className="text-xl font-black text-white">
                                        {analystPerspective.stance_summary}
                                    </div>
                                    {analystPerspective.plain_language_summary && (
                                        <p className="max-w-3xl text-base leading-7 text-indigo-100">
                                            {analystPerspective.plain_language_summary}
                                        </p>
                                    )}
                                    <p className="max-w-3xl text-sm leading-7 text-slate-300">
                                        {analystPerspective.rationale_summary}
                                    </p>
                                </div>
                                <div className="px-3 py-2 rounded-2xl border border-indigo-400/20 bg-slate-950/50 min-w-[180px]">
                                    <div className="text-[9px] font-black uppercase tracking-[0.18em] text-slate-500">Stance</div>
                                    <div className="mt-1 text-sm font-black text-indigo-100">
                                        {formatLabel(analystPerspective.stance)}
                                    </div>
                                </div>
                            </div>
                            {analystEvidence.length > 0 && (
                                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                    {analystEvidence.map((item) => (
                                        <div
                                            key={`${item.label}-${item.timeframe ?? 'na'}`}
                                            className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4"
                                        >
                                            <div className="flex items-center justify-between gap-3">
                                                <span className="text-[10px] font-black uppercase tracking-[0.18em] text-slate-500">
                                                    {item.label}
                                                </span>
                                                {item.timeframe && (
                                                    <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-600">
                                                        {item.timeframe}
                                                    </span>
                                                )}
                                            </div>
                                            {item.value_text && (
                                                <div className="mt-2 text-lg font-mono font-bold text-indigo-200">
                                                    {item.value_text}
                                                </div>
                                            )}
                                            <p className="mt-2 text-xs leading-6 text-slate-400">
                                                {item.rationale}
                                            </p>
                                        </div>
                                    ))}
                                </div>
                            )}
                            {analystSignalExplainers.length > 0 && (
                                <div className="space-y-3">
                                    <div className="flex items-center gap-2">
                                        <Sparkles size={14} className="text-indigo-300 opacity-80" />
                                        <span className="text-[10px] font-black uppercase tracking-[0.18em] text-slate-500">
                                            Simple Signal Guide
                                        </span>
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                        {analystSignalExplainers.map((item) => (
                                            <div
                                                key={`${item.signal}-${item.timeframe ?? 'na'}`}
                                                className="rounded-2xl border border-indigo-500/15 bg-indigo-500/[0.05] p-4"
                                            >
                                                <div className="flex items-start justify-between gap-3">
                                                    <div>
                                                        <div className="text-[10px] font-black uppercase tracking-[0.18em] text-indigo-200">
                                                            {item.plain_name}
                                                        </div>
                                                        <div className="mt-1 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
                                                            {item.signal}
                                                        </div>
                                                    </div>
                                                    <div className="text-right">
                                                        {item.timeframe && (
                                                            <div className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-600">
                                                                {item.timeframe}
                                                            </div>
                                                        )}
                                                        {item.value_text && (
                                                            <div className="mt-1 text-sm font-mono font-bold text-indigo-100">
                                                                {item.value_text}
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                                <p className="mt-3 text-xs leading-6 text-slate-300">
                                                    {item.what_it_means_now}
                                                </p>
                                                <p className="mt-2 text-[11px] leading-5 text-slate-400">
                                                    {item.why_it_matters_now}
                                                </p>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
                                    <div className="text-[9px] font-black uppercase tracking-[0.18em] text-slate-500">Trigger</div>
                                    <div className="mt-2 text-sm leading-6 text-slate-300">
                                        {analystPerspective.trigger_condition ?? 'No explicit trigger detected.'}
                                    </div>
                                </div>
                                <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
                                    <div className="text-[9px] font-black uppercase tracking-[0.18em] text-slate-500">Invalidation</div>
                                    <div className="mt-2 text-sm leading-6 text-slate-300">
                                        {analystPerspective.invalidation_condition ?? 'No explicit invalidation level available.'}
                                    </div>
                                    {analystInvalidationLevel && (
                                        <div className="mt-2 text-[10px] font-black uppercase tracking-[0.16em] text-rose-300">
                                            Level {analystInvalidationLevel}
                                        </div>
                                    )}
                                </div>
                                <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
                                    <div className="text-[9px] font-black uppercase tracking-[0.18em] text-slate-500">Validation Note</div>
                                    <div className="mt-2 text-sm leading-6 text-slate-300">
                                        {analystPerspective.validation_note ?? 'No validation warning was supplied.'}
                                    </div>
                                </div>
                                <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
                                    <div className="text-[9px] font-black uppercase tracking-[0.18em] text-slate-500">Confidence Note</div>
                                    <div className="mt-2 text-sm leading-6 text-slate-300">
                                        {analystPerspective.confidence_note ?? 'Confidence follows the deterministic calibration output.'}
                                    </div>
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="text-base text-slate-400 leading-relaxed">
                            Structured analyst perspective is not available yet.
                        </div>
                    )}
                    <div className="flex flex-wrap gap-2 mt-6">
                        {reportData.summary_tags.length > 0 ? (
                            reportData.summary_tags.map((tag) => (
                                <span key={tag} className="px-3 py-1 bg-indigo-500/10 border border-indigo-500/20 rounded-full text-[10px] font-bold text-indigo-300 uppercase tracking-wider">
                                    #{tag.replace('_', ' ')}
                                </span>
                            ))
                        ) : (
                            <span className="text-xs text-slate-500">No summary tags available.</span>
                        )}
                    </div>
                </section>

            </section>

            {(hasEvidenceIndicators || indicatorSeriesId) && (
                <section className="space-y-4">
                    <div className="flex items-center gap-2">
                        <Zap size={14} className="text-amber-300 opacity-70" />
                        <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">Setup Evidence</span>
                    </div>
                    {momentumFdRiskHint && (
                        <div className="flex items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[10px] font-bold uppercase text-amber-200">
                            <AlertTriangle size={14} className="text-amber-300" />
                            <span>Risk Hint: {momentumFdRiskHint}</span>
                        </div>
                    )}
                    {hasEvidenceIndicators ? (
                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                            {(visibleIndicators.rsi || visibleIndicators.fd) && (
                                <div className="space-y-3 flex flex-col h-full lg:col-span-2">
                                    <div className="flex items-center justify-between text-[10px] font-black text-slate-500 uppercase">
                                        <span>Momentum & Extremes</span>
                                        {momentumTimeframe && (
                                            <span className="text-[9px] text-slate-600 uppercase">
                                                {momentumTimeframe.toUpperCase()}
                                            </span>
                                        )}
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 flex-1">
                                        {visibleIndicators.rsi && (
                                            <div className="relative overflow-hidden flex flex-col justify-between h-full bg-slate-950/70 border border-slate-800 rounded-xl p-4">
                                                <div className="flex items-start justify-between gap-3 mb-3">
                                                    <div>
                                                        <div className="text-[9px] font-black text-slate-500 uppercase">RSI (14)</div>
                                                        <div
                                                            className={`text-xl font-mono font-bold ${tonePalette[momentumRsiDescriptor.tone].value} ${tonePalette[momentumRsiDescriptor.tone].glow}`}
                                                        >
                                                            {formatIndicatorValue(momentumRsiValue)}
                                                        </div>
                                                        <div className="text-[10px] text-transparent uppercase select-none pointer-events-none">
                                                            Spacer
                                                        </div>
                                                    </div>
                                                    <span
                                                        className={`px-2 py-1 rounded-full border text-[9px] font-bold uppercase tracking-wide ${tonePalette[momentumRsiDescriptor.tone].badge}`}
                                                    >
                                                        {momentumRsiDescriptor.label}
                                                    </span>
                                                </div>
                                                <div className="flex items-end justify-between gap-3 flex-1">
                                                    <div className="flex flex-col h-full space-y-1">
                                                        <div className="text-[10px] text-slate-500 uppercase">
                                                            Momentum State
                                                        </div>
                                                        <div className="max-w-[150px] text-[11px] leading-5 text-slate-300 flex-1">
                                                            {momentumRsiDescriptor.meaning}
                                                        </div>
                                                        <div className="text-[10px] font-bold uppercase tracking-wide text-amber-200 mt-auto pt-2">
                                                            {momentumRsiDescriptor.tacticalReadout}
                                                        </div>
                                                    </div>
                                                    <div className="flex flex-col justify-end shrink-0">
                                                        {rsiSparkline ? (
                                                            <svg width={120} height={32} viewBox="0 0 120 32" className="flex-none">
                                                                <polyline
                                                                    points={rsiSparkline}
                                                                    fill="none"
                                                                    stroke={tonePalette[momentumRsiDescriptor.tone].spark}
                                                                    strokeWidth={2}
                                                                />
                                                            </svg>
                                                        ) : (
                                                            <div className="text-[10px] text-slate-600 uppercase">No trend</div>
                                                        )}
                                                    </div>
                                                </div>
                                            </div>
                                        )}
                                        {visibleIndicators.fd && (
                                            <div className="relative overflow-hidden flex flex-col justify-between h-full bg-slate-950/70 border border-slate-800 rounded-xl p-4">
                                                <div className="flex items-start justify-between gap-3 mb-3">
                                                    <div>
                                                        <div className="text-[9px] font-black text-slate-500 uppercase">FD Z-Score</div>
                                                        <div
                                                            className={`text-xl font-mono font-bold ${tonePalette[momentumFdDescriptor.tone].value} ${tonePalette[momentumFdDescriptor.tone].glow}`}
                                                        >
                                                            {formatIndicatorValue(momentumFdValue)}
                                                        </div>
                                                        <div className="text-[10px] text-transparent uppercase select-none pointer-events-none">
                                                            Spacer
                                                        </div>
                                                    </div>
                                                    <span
                                                        className={`px-2 py-1 rounded-full border text-[9px] font-bold uppercase tracking-wide ${tonePalette[momentumFdDescriptor.tone].badge}`}
                                                    >
                                                        {momentumFdDescriptor.label}
                                                    </span>
                                                </div>
                                                <div className="flex items-end justify-between gap-3 flex-1">
                                                    <div className="flex flex-col h-full space-y-1">
                                                        <div className="text-[10px] text-slate-500 uppercase">
                                                            Deviation State
                                                        </div>
                                                        <div className="max-w-[150px] text-[11px] leading-5 text-slate-300 flex-1">
                                                            {momentumFdDescriptor.meaning}
                                                        </div>
                                                        <div className="text-[10px] font-bold uppercase tracking-wide text-amber-200 mt-auto pt-2">
                                                            {momentumFdDescriptor.tacticalReadout}
                                                        </div>
                                                    </div>
                                                    <div className="flex flex-col justify-end shrink-0">
                                                        {fdSparkline ? (
                                                            <svg width={120} height={32} viewBox="0 0 120 32" className="flex-none">
                                                                <polyline
                                                                    points={fdSparkline}
                                                                    fill="none"
                                                                    stroke={tonePalette[momentumFdDescriptor.tone].spark}
                                                                    strokeWidth={2}
                                                                />
                                                            </svg>
                                                        ) : (
                                                            <div className="text-[10px] text-slate-600 uppercase">No trend</div>
                                                        )}
                                                    </div>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}
                            {visibleIndicators.macd && (
                                <div className="space-y-3 flex flex-col h-full lg:col-span-1">
                                    <div className="flex items-center justify-between text-[10px] font-black text-slate-500 uppercase">
                                        <span>Trend & Momentum</span>
                                        {momentumTimeframe && (
                                            <span className="text-[9px] text-slate-600 uppercase">
                                                {momentumTimeframe.toUpperCase()}
                                            </span>
                                        )}
                                    </div>
                                    <div className="grid grid-cols-1 gap-4 flex-1">
                                        <div className="relative overflow-hidden flex flex-col justify-between h-full bg-slate-950/70 border border-slate-800 rounded-xl p-4">
                                            <div className="flex items-start justify-between gap-3 mb-3">
                                                <div>
                                                    <div className="text-[9px] font-black text-slate-500 uppercase">MACD</div>
                                                    <div
                                                        className={`text-xl font-mono font-bold ${tonePalette[macdTone.tone].value} ${tonePalette[macdTone.tone].glow}`}
                                                    >
                                                        {formatIndicatorValue(latestMacd)}
                                                    </div>
                                                    <div className="text-[10px] text-slate-500 uppercase">
                                                        Signal Line: {formatIndicatorValue(latestMacdSignal)}
                                                    </div>
                                                </div>
                                                <span
                                                    className={`px-2 py-1 rounded-full border text-[9px] font-bold uppercase tracking-wide ${tonePalette[macdTone.tone].badge}`}
                                                >
                                                    {macdTone.label}
                                                </span>
                                            </div>
                                            <div className="flex items-end justify-between gap-3 flex-1">
                                                <div className="flex flex-col h-full space-y-1">
                                                    <div className="text-[10px] text-slate-500 uppercase">
                                                        Momentum State
                                                    </div>
                                                    <div className="max-w-[150px] text-[11px] leading-5 text-slate-300 flex-1">
                                                        {macdTone.meaning}
                                                    </div>
                                                    <div className="text-[10px] font-bold uppercase tracking-wide text-amber-200 mt-auto pt-2">
                                                        {macdTone.tacticalReadout}
                                                    </div>
                                                </div>
                                                <div className="flex flex-col justify-end shrink-0">
                                                    {macdSparkline ? (
                                                        <svg width={120} height={32} viewBox="0 0 120 32" className="flex-none">
                                                            <polyline
                                                                points={macdSparkline}
                                                                fill="none"
                                                                stroke={tonePalette[macdTone.tone].spark}
                                                                strokeWidth={2}
                                                            />
                                                        </svg>
                                                    ) : (
                                                        <div className="text-[10px] text-slate-600 uppercase">No trend</div>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    ) : (
                        <div className="text-xs text-slate-500">
                            Indicator evidence unavailable for this run.
                        </div>
                    )}
                </section>
            )}

            <section className="space-y-4">
                {timeseriesBundleData && (
                    <div className="bg-slate-950/40 border border-slate-800 rounded-xl p-4">
                        <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
                            <div className="flex items-center gap-2">
                                <Layers size={14} className="text-cyan-400 opacity-50" />
                                <span className={sectionHeaderTextClass}>Multi-pane Chart Stack</span>
                            </div>
                            <div className="flex flex-wrap items-center gap-4">
                                {availableTimeseriesFrames.length > 0 ? (
                                    <div className="flex items-center bg-slate-800/50 rounded-lg p-0.5 border border-slate-700/50">
                                        {availableTimeseriesFrames.map((frame) => (
                                            <button
                                                key={frame}
                                                onClick={() => setPriceTimeframe(frame)}
                                                className={`px-2 py-1 rounded text-[9px] font-bold transition-all ${priceTimeframe === frame
                                                    ? 'bg-cyan-500/20 text-cyan-400 shadow-[0_0_10px_rgba(34,211,238,0.1)]'
                                                    : 'text-slate-500 hover:text-slate-300'
                                                    }`}
                                            >
                                                {frame.toUpperCase()}
                                            </button>
                                        ))}
                                    </div>
                                ) : (
                                    <div className="text-[10px] text-slate-500 uppercase">
                                        No OHLC frames
                                    </div>
                                )}
                                {indicatorTimeframe && (
                                    <div className="text-[10px] font-bold uppercase text-slate-600">
                                        Indicators: {indicatorTimeframe.toUpperCase()}
                                    </div>
                                )}
                                {timeseriesWindow && (
                                    <div className="text-[10px] font-bold uppercase text-slate-600">
                                        {timeseriesWindow.start} → {timeseriesWindow.end}
                                    </div>
                                )}
                            </div>
                        </div>

                        <div
                            ref={chartStackRef}
                            className="relative rounded-xl border border-slate-800/70 bg-slate-950/55"
                        >
                            <div className="divide-y divide-slate-800/60">
                                <div className="px-4 py-3">
                                    <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                                        <div className="text-[9px] font-black text-slate-500 uppercase">
                                            Price Action (OHLCV)
                                        </div>
                                        {priceOverlays.length > 0 && (
                                            <div className="flex flex-wrap items-center gap-3 text-[9px] text-slate-500 uppercase">
                                                {priceOverlays.map((overlay) => (
                                                    <span key={overlay.id} className="inline-flex items-center gap-1">
                                                        <span
                                                            className="h-2 w-2 rounded-full"
                                                            style={{ backgroundColor: overlay.color }}
                                                        />
                                                        {overlay.id}
                                                    </span>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                    <TechnicalCandlestickChart
                                        candles={candlestickSeries}
                                        volumes={volumeSeries}
                                        overlays={priceOverlays}
                                        height={CHART_PANE_HEIGHTS.price}
                                        showTime={isIntradayTimeseries}
                                        showTimeScale={bottomTimeScalePane === 'price'}
                                        showVolume={false}
                                        syncId="price"
                                        syncState={crosshairSync}
                                    />
                                </div>

                                <div className="px-4 py-3">
                                    <div className="text-[9px] font-black text-slate-500 uppercase mb-2">Volume</div>
                                    {volumeHistogram.length > 0 ? (
                                        <TechnicalIndicatorChart
                                            lines={[]}
                                            histograms={volumeHistogram}
                                            height={CHART_PANE_HEIGHTS.volume}
                                            showTime={isIntradayTimeseries}
                                            showTimeScale={bottomTimeScalePane === 'volume'}
                                            histogramScaleMargins={{ top: 0.2, bottom: 0.08 }}
                                            syncId="volume"
                                            syncState={crosshairSync}
                                        />
                                    ) : (
                                        <div className="text-xs text-slate-500">Volume data unavailable.</div>
                                    )}
                                </div>

                                <div className="px-4 py-3">
                                    <div className="text-[9px] font-black text-slate-500 uppercase mb-2">RSI (14)</div>
                                    {indicatorAvailability.rsi ? (
                                        <TechnicalIndicatorChart
                                            lines={rsiLines}
                                            priceLines={rsiPriceLines}
                                            height={CHART_PANE_HEIGHTS.rsi}
                                            showTime={isIntradayTimeseries}
                                            showTimeScale={bottomTimeScalePane === 'rsi'}
                                            syncId="rsi"
                                            syncState={crosshairSync}
                                        />
                                    ) : (
                                        <div className="text-xs text-slate-500">RSI data unavailable.</div>
                                    )}
                                </div>

                                <div className="px-4 py-3">
                                    <div className="text-[9px] font-black text-slate-500 uppercase mb-2">MACD</div>
                                    {indicatorAvailability.macd ? (
                                        <TechnicalIndicatorChart
                                            lines={macdLines}
                                            histograms={macdHistogram}
                                            priceLines={macdPriceLines}
                                            height={CHART_PANE_HEIGHTS.macd}
                                            showTime={isIntradayTimeseries}
                                            showTimeScale={bottomTimeScalePane === 'macd'}
                                            syncId="macd"
                                            syncState={crosshairSync}
                                        />
                                    ) : (
                                        <div className="text-xs text-slate-500">MACD data unavailable.</div>
                                    )}
                                </div>

                                <div className="px-4 py-3">
                                    <div className="text-[9px] font-black text-slate-500 uppercase mb-2">FracDiff</div>
                                    {indicatorAvailability.fd ? (
                                        <TechnicalIndicatorChart
                                            lines={fdLines}
                                            priceLines={fdPriceLines}
                                            height={CHART_PANE_HEIGHTS.fracdiff}
                                            showTime={isIntradayTimeseries}
                                            showTimeScale={bottomTimeScalePane === 'fd'}
                                            syncId="fd"
                                            syncState={crosshairSync}
                                        />
                                    ) : (
                                        <div className="text-xs text-slate-500">Fracdiff data unavailable.</div>
                                    )}
                                </div>
                            </div>

                            {tooltipPosition && tooltipPayload && (
                                <div
                                    className="pointer-events-none absolute z-20 w-60 rounded-xl border border-slate-700/60 bg-slate-950/80 backdrop-blur-md p-3 text-[10px] text-slate-100 shadow-lg"
                                    style={{ left: tooltipPosition.x, top: tooltipPosition.y }}
                                >
                                    <div className="text-[9px] font-black uppercase text-slate-400 mb-2">
                                        {formatTooltipTimestamp(tooltipPayload.time, isIntradayTimeseries)}
                                    </div>
                                    <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                                        <div>O: {tooltipPayload.candle ? formatPrice(tooltipPayload.candle.open) : 'n/a'}</div>
                                        <div>H: {tooltipPayload.candle ? formatPrice(tooltipPayload.candle.high) : 'n/a'}</div>
                                        <div>L: {tooltipPayload.candle ? formatPrice(tooltipPayload.candle.low) : 'n/a'}</div>
                                        <div>C: {tooltipPayload.candle ? formatPrice(tooltipPayload.candle.close) : 'n/a'}</div>
                                    </div>
                                    <div className="mt-2 border-t border-slate-800 pt-2 space-y-1">
                                        <div className="flex items-center justify-between">
                                            <span className="text-slate-400">Volume</span>
                                            <span>{formatVolume(tooltipPayload.volume as number | null)}</span>
                                        </div>
                                        <div className="flex items-center justify-between">
                                            <span className="text-slate-400">RSI</span>
                                            <span>{formatIndicatorValue(tooltipPayload.rsi as number | null)}</span>
                                        </div>
                                        <div className="flex items-center justify-between">
                                            <span className="text-slate-400">MACD</span>
                                            <span>{formatIndicatorValue(tooltipPayload.macd as number | null)}</span>
                                        </div>
                                        <div className="flex items-center justify-between">
                                            <span className="text-slate-400">Signal Line</span>
                                            <span>{formatIndicatorValue(tooltipPayload.macdSignal as number | null)}</span>
                                        </div>
                                        <div className="flex items-center justify-between">
                                            <span className="text-slate-400">Histogram</span>
                                            <span>{formatIndicatorValue(tooltipPayload.macdHist as number | null)}</span>
                                        </div>
                                        <div className="flex items-center justify-between">
                                            <span className="text-slate-400">FracDiff</span>
                                            <span>{formatIndicatorValue(tooltipPayload.fd as number | null)}</span>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                        <div className="mt-2 flex justify-end text-[9px] text-slate-500">
                            <a
                                href="https://www.tradingview.com/"
                                target="_blank"
                                rel="noreferrer"
                                className="hover:text-slate-300 underline"
                            >
                                Charts by TradingView
                            </a>
                        </div>
                    </div>
                )}
            </section>

            <section className="space-y-4">
                <div className="flex items-center gap-2">
                    <AlertTriangle size={14} className="text-rose-400 opacity-70" />
                    <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">Diagnostics</span>
                </div>
                {timeseriesBundleError && (
                    <div className="text-xs text-rose-300">
                        Unable to load OHLC series. Please retry later.
                    </div>
                )}
                {indicatorSeriesError && (
                    <div className="text-xs text-rose-300">
                        Unable to load indicator series. Please retry later.
                    </div>
                )}
                {(isDegraded || degradedReasons.length > 0) && (
                    <section className="tech-card p-5 border border-rose-500/20 bg-rose-500/5">
                        <div className="flex items-center gap-2 mb-3">
                            <AlertTriangle size={16} className="text-rose-400" />
                            <span className="text-xs font-black text-rose-200 uppercase tracking-[0.2em]">Degraded Data Path</span>
                        </div>
                        <div className="text-xs text-slate-300">
                            One or more data sources were degraded or missing. Review the notes below before taking action.
                        </div>
                        {degradedReasons.length > 0 && (
                            <div className="flex flex-wrap gap-2 mt-3">
                                {degradedReasons.map((reason) => (
                                    <span key={reason} className="px-3 py-1 bg-rose-500/10 border border-rose-500/20 rounded-full text-[10px] font-bold text-rose-200 uppercase tracking-wider">
                                        {reason.replace('_', ' ')}
                                    </span>
                                ))}
                            </div>
                        )}
                    </section>
                )}

                {timeseriesSummary && (
                    <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                        <div className="text-[9px] font-black text-slate-500 uppercase mb-2">OHLC Series</div>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-slate-200">
                            <div>Frames: {timeseriesSummary.frameCount}</div>
                            <div>Max Points: {timeseriesSummary.maxPoints}</div>
                            <div>Selected: {priceTimeframe ? priceTimeframe.toUpperCase() : 'n/a'}</div>
                        </div>
                        {timeseriesSummary.degradedReasons.length > 0 && (
                            <div className="mt-2 text-[10px] text-amber-300">
                                Degraded: {timeseriesSummary.degradedReasons.join(', ')}
                            </div>
                        )}
                    </div>
                )}

                {indicatorSeriesSummary && (
                    <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                        <div className="text-[9px] font-black text-slate-500 uppercase mb-2">Indicator Series</div>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-slate-200">
                            <div>Frames: {indicatorSeriesSummary.timeframeCount}</div>
                            <div>Series: {indicatorSeriesSummary.seriesTotal}</div>
                            <div>Max Points: {indicatorSeriesSummary.maxPoints}</div>
                        </div>
                        {indicatorSeriesSummary.degradedReasons.length > 0 && (
                            <div className="mt-2 text-[10px] text-amber-300">
                                Degraded: {indicatorSeriesSummary.degradedReasons.join(', ')}
                            </div>
                        )}
                    </div>
                )}

                {hasMomentumExtremes && (
                    <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                        <div className="text-[9px] font-black text-slate-500 uppercase mb-2">Raw Momentum & Extremes Data</div>
                        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-xs text-slate-200">
                            <div>
                                Timeframe: {momentumTimeframe ? momentumTimeframe.toUpperCase() : 'n/a'}
                            </div>
                            <div>
                                Source: {momentumExtremes?.source ?? 'n/a'}
                            </div>
                            <div>
                                FD Z-Score: {formatIndicatorValue(momentumFdValue)}
                            </div>
                            <div>
                                RSI (14): {formatIndicatorValue(momentumRsiValue)}
                            </div>
                        </div>
                    </div>
                )}
            </section>

            <section className="space-y-4">
                <div className="flex items-center gap-2">
                    <Layers size={14} className="text-cyan-400 opacity-70" />
                    <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">Other</span>
                </div>

                {alertsId && (
                    <section className="tech-card overflow-hidden transition-all duration-300">
                        <button
                            onClick={() => setShowAlerts(!showAlerts)}
                            className="w-full flex items-center justify-between p-4 bg-slate-900/20 hover:bg-slate-900/40 transition-colors"
                        >
                            <div className="flex items-center gap-2">
                                <Bell size={14} className="text-slate-500" />
                                <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Alert Signals</span>
                            </div>
                            <div className="flex items-center gap-4">
                                {showAlerts && isAlertsLoadingState && (
                                    <AgentLoadingState
                                        type="header"
                                        title="Loading Alerts..."
                                        colorClass="text-cyan-400"
                                    />
                                )}
                                {alertsSummary && (
                                    <div className="flex items-center gap-2 text-[9px] font-bold uppercase text-slate-500">
                                        <span>Total {alertsSummary.total}</span>
                                        <span className="text-rose-300">C {alertsSummary.severityCounts.critical}</span>
                                        <span className="text-amber-300">W {alertsSummary.severityCounts.warning}</span>
                                        <span className="text-slate-400">I {alertsSummary.severityCounts.info}</span>
                                    </div>
                                )}
                                {showAlerts ? (
                                    <ChevronUp size={16} className="text-slate-500" />
                                ) : (
                                    <ChevronDown size={16} className="text-slate-500" />
                                )}
                            </div>
                        </button>

                        {showAlerts && (
                            <div className="p-6 space-y-5 animate-in slide-in-from-top-2 duration-300">
                                {alertsError && (
                                    <div className="text-xs text-rose-300">
                                        Unable to load alerts. Please retry later.
                                    </div>
                                )}

                                {!alertsData && !alertsError && (
                                    <div className="text-xs text-slate-500">
                                        Alert data will appear here once loaded.
                                    </div>
                                )}

                                {alertsData && alertsSummary && (
                                    <>
                                        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Total Alerts</div>
                                                <div className="text-lg font-black text-white">{alertsSummary.total}</div>
                                            </div>
                                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Critical</div>
                                                <div className="text-lg font-black text-rose-300">{alertsSummary.severityCounts.critical}</div>
                                            </div>
                                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Warning</div>
                                                <div className="text-lg font-black text-amber-300">{alertsSummary.severityCounts.warning}</div>
                                            </div>
                                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Info</div>
                                                <div className="text-lg font-black text-slate-200">{alertsSummary.severityCounts.info}</div>
                                            </div>
                                        </div>

                                        {alertsSummary.generatedAt && (
                                            <div className="text-[10px] text-slate-500">
                                                Generated at {alertsSummary.generatedAt}
                                            </div>
                                        )}

                                        {alertsData.degraded_reasons && alertsData.degraded_reasons.length > 0 && (
                                            <div className="flex flex-wrap gap-2">
                                                {alertsData.degraded_reasons.map((reason) => (
                                                    <span key={reason} className="px-3 py-1 bg-rose-500/10 border border-rose-500/20 rounded-full text-[10px] font-bold text-rose-200 uppercase tracking-wider">
                                                        {reason.replace('_', ' ')}
                                                    </span>
                                                ))}
                                            </div>
                                        )}

                                        {alertsSummary.alerts.length > 0 ? (
                                            <div className="space-y-3">
                                                {alertsSummary.alerts.map((alert, idx) => {
                                                    const tone = getAlertSeverityTone(alert.severity);
                                                    return (
                                                        <div
                                                            key={`${alert.code}-${idx}`}
                                                            className="bg-slate-950/50 p-4 rounded-xl border border-slate-800 space-y-3"
                                                        >
                                                            <div className="flex items-start justify-between gap-4">
                                                                <div>
                                                                    <div className="text-[9px] font-black uppercase tracking-widest text-slate-500 mb-1">
                                                                        {alert.timeframe.toUpperCase()} · {formatLabel(alert.code)}
                                                                    </div>
                                                                    <div className="text-sm font-black text-white">{alert.title}</div>
                                                                    {alert.message && (
                                                                        <div className="text-xs text-slate-400 mt-1">
                                                                            {alert.message}
                                                                        </div>
                                                                    )}
                                                                </div>
                                                                <span
                                                                    className={`px-2.5 py-1 rounded-full border text-[9px] font-black uppercase tracking-widest ${tone.badge}`}
                                                                >
                                                                    {tone.label}
                                                                </span>
                                                            </div>
                                                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-[10px] text-slate-300">
                                                                {alert.value !== null && alert.value !== undefined && (
                                                                    <div>
                                                                        Value: {formatIndicatorValue(alert.value)}
                                                                    </div>
                                                                )}
                                                                {alert.threshold !== null && alert.threshold !== undefined && (
                                                                    <div>
                                                                        Threshold: {formatIndicatorValue(alert.threshold)}
                                                                    </div>
                                                                )}
                                                                {alert.direction && (
                                                                    <div>
                                                                        Direction: {formatLabel(alert.direction)}
                                                                    </div>
                                                                )}
                                                                {alert.triggered_at && (
                                                                    <div>
                                                                        Triggered: {alert.triggered_at}
                                                                    </div>
                                                                )}
                                                                {alert.source && (
                                                                    <div>
                                                                        Source: {formatLabel(alert.source)}
                                                                    </div>
                                                                )}
                                                            </div>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        ) : (
                                            <div className="text-xs text-slate-500">
                                                No alert signals detected for the current window.
                                            </div>
                                        )}
                                    </>
                                )}
                            </div>
                        )}
                    </section>
                )}

                {featurePackId && (
                    <section className="tech-card overflow-hidden transition-all duration-300">
                        <button
                            onClick={() => setShowFeaturePack(!showFeaturePack)}
                            className="w-full flex items-center justify-between p-4 bg-slate-900/20 hover:bg-slate-900/40 transition-colors"
                        >
                            <div className="flex items-center gap-2">
                                <Layers size={14} className="text-slate-500" />
                                <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Feature Pack</span>
                            </div>
                            <div className="flex items-center gap-4">
                                {showFeaturePack && isFeaturePackLoading && (
                                    <AgentLoadingState
                                        type="header"
                                        title="Loading Feature Pack..."
                                        colorClass="text-cyan-400"
                                    />
                                )}
                                {showFeaturePack ? (
                                    <ChevronUp size={16} className="text-slate-500" />
                                ) : (
                                    <ChevronDown size={16} className="text-slate-500" />
                                )}
                            </div>
                        </button>

                        {showFeaturePack && (
                            <div className="p-6 space-y-5 animate-in slide-in-from-top-2 duration-300">
                                {featurePackError && (
                                    <div className="text-xs text-rose-300">
                                        Unable to load feature pack. Please retry later.
                                    </div>
                                )}

                                {!featurePackData && !featurePackError && (
                                    <div className="text-xs text-slate-500">
                                        Feature pack data will appear here once loaded.
                                    </div>
                                )}

                                {featurePackData && featurePackSummary && (
                                    <>
                                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Timeframes</div>
                                                <div className="text-lg font-black text-white">{featurePackSummary.summaries.length}</div>
                                            </div>
                                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Classic Indicators</div>
                                                <div className="text-lg font-black text-white">{featurePackSummary.classicTotal}</div>
                                            </div>
                                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Quant Features</div>
                                                <div className="text-lg font-black text-white">{featurePackSummary.quantTotal}</div>
                                            </div>
                                        </div>

                                        {featurePackData.degraded_reasons && featurePackData.degraded_reasons.length > 0 && (
                                            <div className="flex flex-wrap gap-2">
                                                {featurePackData.degraded_reasons.map((reason) => (
                                                    <span key={reason} className="px-3 py-1 bg-rose-500/10 border border-rose-500/20 rounded-full text-[10px] font-bold text-rose-200 uppercase tracking-wider">
                                                        {reason.replace('_', ' ')}
                                                    </span>
                                                ))}
                                            </div>
                                        )}

                                        <div className="grid grid-cols-1 gap-4">
                                            {featurePackSummary.summaries.map((frame) => (
                                                <div key={frame.timeframe} className="bg-slate-950/50 p-5 rounded-xl border border-slate-800 space-y-3">
                                                    <div className="flex items-center justify-between">
                                                        <div className="text-xs font-black uppercase tracking-widest text-slate-400">
                                                            {formatLabel(frame.timeframe)}
                                                        </div>
                                                        <div className="text-[10px] text-slate-500 font-bold uppercase">
                                                            Classic {frame.classicCount} · Quant {frame.quantCount}
                                                        </div>
                                                    </div>
                                                    <div>
                                                        <div className="text-[9px] font-black text-slate-500 uppercase mb-2">Classic Highlights</div>
                                                        {renderIndicatorHighlights(frame.classicHighlights)}
                                                    </div>
                                                    <div>
                                                        <div className="text-[9px] font-black text-slate-500 uppercase mb-2">Quant Highlights</div>
                                                        {renderIndicatorHighlights(frame.quantHighlights)}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </>
                                )}
                            </div>
                        )}
                    </section>
                )}

                {patternPackId && (
                    <section className="tech-card overflow-hidden transition-all duration-300">
                        <button
                            onClick={() => setShowPatternPack(!showPatternPack)}
                            className="w-full flex items-center justify-between p-4 bg-slate-900/20 hover:bg-slate-900/40 transition-colors"
                        >
                            <div className="flex items-center gap-2">
                                <Layers size={14} className="text-slate-500" />
                                <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Pattern Pack</span>
                            </div>
                            <div className="flex items-center gap-4">
                                {showPatternPack && isPatternPackLoading && (
                                    <AgentLoadingState
                                        type="header"
                                        title="Loading Pattern Pack..."
                                        colorClass="text-cyan-400"
                                    />
                                )}
                                {showPatternPack ? (
                                    <ChevronUp size={16} className="text-slate-500" />
                                ) : (
                                    <ChevronDown size={16} className="text-slate-500" />
                                )}
                            </div>
                        </button>

                        {showPatternPack && (
                            <div className="p-6 space-y-5 animate-in slide-in-from-top-2 duration-300">
                                {patternPackError && (
                                    <div className="text-xs text-rose-300">
                                        Unable to load pattern pack. Please retry later.
                                    </div>
                                )}

                                {!patternPackData && !patternPackError && (
                                    <div className="text-xs text-slate-500">
                                        Pattern pack data will appear here once loaded.
                                    </div>
                                )}

                                {patternPackData && patternPackSummary && (
                                    <>
                                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Timeframes</div>
                                                <div className="text-lg font-black text-white">{patternPackSummary.summaries.length}</div>
                                            </div>
                                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Levels</div>
                                                <div className="text-lg font-black text-white">{patternPackSummary.totalLevels}</div>
                                            </div>
                                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Flags</div>
                                                <div className="text-lg font-black text-white">{patternPackSummary.totalFlags}</div>
                                            </div>
                                        </div>

                                        {patternPackData.degraded_reasons && patternPackData.degraded_reasons.length > 0 && (
                                            <div className="flex flex-wrap gap-2">
                                                {patternPackData.degraded_reasons.map((reason) => (
                                                    <span key={reason} className="px-3 py-1 bg-rose-500/10 border border-rose-500/20 rounded-full text-[10px] font-bold text-rose-200 uppercase tracking-wider">
                                                        {reason.replace('_', ' ')}
                                                    </span>
                                                ))}
                                            </div>
                                        )}

                                        <div className="grid grid-cols-1 gap-4">
                                            {patternPackSummary.summaries.map((frame) => (
                                                <div key={frame.timeframe} className="bg-slate-950/50 p-5 rounded-xl border border-slate-800 space-y-4">
                                                    <div className="flex items-center justify-between">
                                                        <div className="text-xs font-black uppercase tracking-widest text-slate-400">
                                                            {formatLabel(frame.timeframe)}
                                                        </div>
                                                        <div className="text-[10px] text-slate-500 font-bold uppercase">
                                                            Supports {frame.supportCount} · Resist {frame.resistanceCount} · Flags {frame.flagCount}
                                                        </div>
                                                    </div>

                                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                        <div>
                                                            <div className="text-[9px] font-black text-slate-500 uppercase mb-2">Support Levels</div>
                                                            {frame.supportLevels.length > 0 ? (
                                                                <div className="space-y-2">
                                                                    {frame.supportLevels.map((level, idx) => (
                                                                        <div key={`${frame.timeframe}-support-${idx}`} className="flex items-center justify-between text-xs text-slate-200">
                                                                            <span>{level.label ? formatLabel(level.label) : 'Support'} @ {formatPrice(level.price)}</span>
                                                                            <span className="text-[10px] text-slate-500">
                                                                                {level.strength !== null && level.strength !== undefined ? `Strength ${level.strength.toFixed(2)}` : 'Strength n/a'}
                                                                            </span>
                                                                        </div>
                                                                    ))}
                                                                </div>
                                                            ) : (
                                                                <div className="text-xs text-slate-500">No support levels detected.</div>
                                                            )}
                                                        </div>
                                                        <div>
                                                            <div className="text-[9px] font-black text-slate-500 uppercase mb-2">Resistance Levels</div>
                                                            {frame.resistanceLevels.length > 0 ? (
                                                                <div className="space-y-2">
                                                                    {frame.resistanceLevels.map((level, idx) => (
                                                                        <div key={`${frame.timeframe}-resistance-${idx}`} className="flex items-center justify-between text-xs text-slate-200">
                                                                            <span>{level.label ? formatLabel(level.label) : 'Resistance'} @ {formatPrice(level.price)}</span>
                                                                            <span className="text-[10px] text-slate-500">
                                                                                {level.strength !== null && level.strength !== undefined ? `Strength ${level.strength.toFixed(2)}` : 'Strength n/a'}
                                                                            </span>
                                                                        </div>
                                                                    ))}
                                                                </div>
                                                            ) : (
                                                                <div className="text-xs text-slate-500">No resistance levels detected.</div>
                                                            )}
                                                        </div>
                                                    </div>

                                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                        <div>
                                                            <div className="text-[9px] font-black text-slate-500 uppercase mb-2">Breakouts</div>
                                                            {frame.breakoutFlags.length > 0 ? (
                                                                <div className="flex flex-wrap gap-2">
                                                                    {frame.breakoutFlags.map((flag, idx) => (
                                                                        <span key={`${frame.timeframe}-breakout-${idx}`} className="px-2.5 py-1 bg-slate-900/60 border border-slate-800 rounded-full text-[10px] font-bold text-slate-200 uppercase tracking-wide">
                                                                            {flag.name} {flag.confidence !== null && flag.confidence !== undefined ? `(${flag.confidence.toFixed(2)})` : ''}
                                                                        </span>
                                                                    ))}
                                                                </div>
                                                            ) : (
                                                                <div className="text-xs text-slate-500">No breakout flags detected.</div>
                                                            )}
                                                        </div>
                                                        <div>
                                                            <div className="text-[9px] font-black text-slate-500 uppercase mb-2">Trendlines</div>
                                                            {frame.trendFlags.length > 0 ? (
                                                                <div className="flex flex-wrap gap-2">
                                                                    {frame.trendFlags.map((flag, idx) => (
                                                                        <span key={`${frame.timeframe}-trend-${idx}`} className="px-2.5 py-1 bg-slate-900/60 border border-slate-800 rounded-full text-[10px] font-bold text-slate-200 uppercase tracking-wide">
                                                                            {flag.name} {flag.confidence !== null && flag.confidence !== undefined ? `(${flag.confidence.toFixed(2)})` : ''}
                                                                        </span>
                                                                    ))}
                                                                </div>
                                                            ) : (
                                                                <div className="text-xs text-slate-500">No trendline flags detected.</div>
                                                            )}
                                                        </div>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </>
                                )}
                            </div>
                        )}
                    </section>
                )}

                {fusionReportId && (
                    <section className="tech-card overflow-hidden transition-all duration-300">
                        <button
                            onClick={() => setShowFusionReport(!showFusionReport)}
                            className="w-full flex items-center justify-between p-4 bg-slate-900/20 hover:bg-slate-900/40 transition-colors"
                        >
                            <div className="flex items-center gap-2">
                                <Layers size={14} className="text-slate-500" />
                                <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Fusion Report</span>
                            </div>
                            <div className="flex items-center gap-4">
                                {showFusionReport &&
                                    (isFusionReportLoading || isDirectionScorecardLoading) && (
                                        <AgentLoadingState
                                            type="header"
                                            title="Loading Fusion Report..."
                                            colorClass="text-cyan-400"
                                        />
                                    )}
                                {showFusionReport ? (
                                    <ChevronUp size={16} className="text-slate-500" />
                                ) : (
                                    <ChevronDown size={16} className="text-slate-500" />
                                )}
                            </div>
                        </button>

                        {showFusionReport && (
                            <div className="p-6 space-y-5 animate-in slide-in-from-top-2 duration-300">
                                {fusionReportError && (
                                    <div className="text-xs text-rose-300">
                                        Unable to load fusion report. Please retry later.
                                    </div>
                                )}

                                {directionScorecardError && (
                                    <div className="text-xs text-rose-300">
                                        Unable to load direction scorecard. Please retry later.
                                    </div>
                                )}

                                {!fusionReportData && !fusionReportError && (
                                    <div className="text-xs text-slate-500">
                                        Fusion report data will appear here once loaded.
                                    </div>
                                )}

                                {fusionReportData && (
                                    <>
                                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Timeframes</div>
                                                <div className="text-lg font-black text-white">{fusionReportSummary?.totalFrames ?? 0}</div>
                                            </div>
                                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Conflicts</div>
                                                <div className="text-lg font-black text-white">{fusionReportData.conflict_reasons?.length ?? 0}</div>
                                            </div>
                                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Confidence</div>
                                                <div className="text-lg font-black text-white">{fusionConfidenceDisplay}</div>
                                                <div className="text-[9px] text-slate-500 uppercase tracking-widest mt-1">{fusionConfidenceLabel}</div>
                                                {fusionRawDisplay && (
                                                    <div className="text-[9px] text-slate-600 uppercase tracking-widest mt-1">
                                                        Raw {fusionRawDisplay}
                                                    </div>
                                                )}
                                            </div>
                                        </div>

                                        {fusionReportData.degraded_reasons && fusionReportData.degraded_reasons.length > 0 && (
                                            <div className="flex flex-wrap gap-2">
                                                {fusionReportData.degraded_reasons.map((reason) => (
                                                    <span key={reason} className="px-3 py-1 bg-rose-500/10 border border-rose-500/20 rounded-full text-[10px] font-bold text-rose-200 uppercase tracking-wider">
                                                        {reason.replace('_', ' ')}
                                                    </span>
                                                ))}
                                            </div>
                                        )}

                                        {fusionReportData.conflict_reasons && fusionReportData.conflict_reasons.length > 0 && (
                                            <div className="flex flex-wrap gap-2">
                                                {fusionReportData.conflict_reasons.map((reason) => (
                                                    <span key={reason} className="px-3 py-1 bg-amber-500/10 border border-amber-500/20 rounded-full text-[10px] font-bold text-amber-200 uppercase tracking-wider">
                                                        {reason.replace('_', ' ')}
                                                    </span>
                                                ))}
                                            </div>
                                        )}

                                        {fusionReportSummary && fusionReportSummary.entries.length > 0 && (
                                            <div className="grid grid-cols-1 gap-4">
                                                {fusionReportSummary.entries.map((entry) => (
                                                    <div key={entry.timeframe} className="bg-slate-950/50 p-5 rounded-xl border border-slate-800 space-y-3">
                                                        <div className="flex items-center justify-between">
                                                            <div className="text-xs font-black uppercase tracking-widest text-slate-400">
                                                                {formatLabel(entry.timeframe)}
                                                            </div>
                                                            <div className="text-[10px] text-slate-500 font-bold uppercase">
                                                                Classic · Quant · Pattern
                                                            </div>
                                                        </div>
                                                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                                            <div className="bg-slate-900/40 p-3 rounded-lg border border-slate-800">
                                                                <div className="text-[9px] text-slate-500 font-bold uppercase mb-1">Classic</div>
                                                                <div className="text-sm font-black text-white">{formatLabel(entry.classic)}</div>
                                                                <div className="text-[10px] text-slate-500">Score {entry.classicScore !== null ? entry.classicScore.toFixed(2) : 'n/a'}</div>
                                                            </div>
                                                            <div className="bg-slate-900/40 p-3 rounded-lg border border-slate-800">
                                                                <div className="text-[9px] text-slate-500 font-bold uppercase mb-1">Quant</div>
                                                                <div className="text-sm font-black text-white">{formatLabel(entry.quant)}</div>
                                                                <div className="text-[10px] text-slate-500">Score {entry.quantScore !== null ? entry.quantScore.toFixed(2) : 'n/a'}</div>
                                                            </div>
                                                            <div className="bg-slate-900/40 p-3 rounded-lg border border-slate-800">
                                                                <div className="text-[9px] text-slate-500 font-bold uppercase mb-1">Pattern</div>
                                                                <div className="text-sm font-black text-white">{formatLabel(entry.pattern)}</div>
                                                                <div className="text-[10px] text-slate-500">Score {entry.patternScore !== null ? entry.patternScore.toFixed(2) : 'n/a'}</div>
                                                            </div>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        )}

                                        {directionScorecardData && scorecardSummary && scorecardSummary.entries.length > 0 && (
                                            <div className="space-y-4">
                                                <div className="flex items-center justify-between">
                                                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">
                                                        Direction Scorecard
                                                    </div>
                                                    <div className="text-[10px] text-slate-500 font-bold uppercase">
                                                        Model {scorecardSummary.modelVersion ?? 'n/a'} · Neutral {scorecardSummary.neutralThreshold.toFixed(2)}
                                                    </div>
                                                </div>
                                                <div className="grid grid-cols-1 gap-4">
                                                    {scorecardSummary.entries.map(({ timeframe, frame }) => (
                                                        <div key={timeframe} className="bg-slate-950/50 p-5 rounded-xl border border-slate-800 space-y-4">
                                                            <div className="flex items-center justify-between">
                                                                <div className="text-xs font-black uppercase tracking-widest text-slate-400">
                                                                    {formatLabel(timeframe)}
                                                                </div>
                                                                <div className="text-[10px] text-slate-500 font-bold uppercase">
                                                                    Total {formatContributionValue(frame.total_score)}
                                                                </div>
                                                            </div>
                                                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                                                <div className="bg-slate-900/40 p-3 rounded-lg border border-slate-800 space-y-2">
                                                                    <div className="text-[9px] text-slate-500 font-bold uppercase">Classic</div>
                                                                    <div className="text-sm font-black text-white">{formatLabel(frame.classic_label)}</div>
                                                                    <div className="text-[10px] text-slate-500">Score {frame.classic_score.toFixed(2)}</div>
                                                                    {renderScorecardContributions(frame.contributions?.classic ?? [])}
                                                                </div>
                                                                <div className="bg-slate-900/40 p-3 rounded-lg border border-slate-800 space-y-2">
                                                                    <div className="text-[9px] text-slate-500 font-bold uppercase">Quant</div>
                                                                    <div className="text-sm font-black text-white">{formatLabel(frame.quant_label)}</div>
                                                                    <div className="text-[10px] text-slate-500">Score {frame.quant_score.toFixed(2)}</div>
                                                                    {renderScorecardContributions(frame.contributions?.quant ?? [])}
                                                                </div>
                                                                <div className="bg-slate-900/40 p-3 rounded-lg border border-slate-800 space-y-2">
                                                                    <div className="text-[9px] text-slate-500 font-bold uppercase">Pattern</div>
                                                                    <div className="text-sm font-black text-white">{formatLabel(frame.pattern_label)}</div>
                                                                    <div className="text-[10px] text-slate-500">Score {frame.pattern_score.toFixed(2)}</div>
                                                                    {renderScorecardContributions(frame.contributions?.pattern ?? [])}
                                                                </div>
                                                            </div>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        {fusionReportData.alignment_report && Object.keys(fusionReportData.alignment_report).length > 0 && (
                                            <div className="text-xs text-slate-400">
                                                Alignment report attached ({Object.keys(fusionReportData.alignment_report).length} fields).
                                            </div>
                                        )}
                                    </>
                                )}
                            </div>
                        )}
                    </section>
                )}

                {verificationReportId && (
                    <section className="tech-card overflow-hidden transition-all duration-300">
                        <button
                            onClick={() =>
                                setShowVerificationReport(!showVerificationReport)
                            }
                            className="w-full flex items-center justify-between p-4 bg-slate-900/20 hover:bg-slate-900/40 transition-colors"
                        >
                            <div className="flex items-center gap-2">
                                <Layers size={14} className="text-slate-500" />
                                <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Verification &amp; Baseline</span>
                            </div>
                            <div className="flex items-center gap-4">
                                {showVerificationReport && isVerificationReportLoading && (
                                    <AgentLoadingState
                                        type="header"
                                        title="Loading Verification Report..."
                                        colorClass="text-cyan-400"
                                    />
                                )}
                                {showVerificationReport ? (
                                    <ChevronUp size={16} className="text-slate-500" />
                                ) : (
                                    <ChevronDown size={16} className="text-slate-500" />
                                )}
                            </div>
                        </button>

                        {showVerificationReport && (
                            <div className="p-6 space-y-5 animate-in slide-in-from-top-2 duration-300">
                                {verificationReportError && (
                                    <div className="text-xs text-rose-300">
                                        Unable to load verification report. Please retry later.
                                    </div>
                                )}

                                {!verificationReportData && !verificationReportError && (
                                    <div className="text-xs text-slate-500">
                                        Verification report data will appear here once loaded.
                                    </div>
                                )}

                                {verificationReportData && (
                                    <>
                                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Baseline Gates</div>
                                                <div className="text-lg font-black text-white">{verificationSummary?.gatesCount ?? 0}</div>
                                            </div>
                                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Robustness Flags</div>
                                                <div className="text-lg font-black text-white">{verificationSummary?.flagsCount ?? 0}</div>
                                            </div>
                                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">As Of</div>
                                                <div className="text-lg font-black text-white">{verificationReportData.as_of}</div>
                                            </div>
                                        </div>

                                        {verificationReportData.degraded_reasons && verificationReportData.degraded_reasons.length > 0 && (
                                            <div className="flex flex-wrap gap-2">
                                                {verificationReportData.degraded_reasons.map((reason) => (
                                                    <span key={reason} className="px-3 py-1 bg-rose-500/10 border border-rose-500/20 rounded-full text-[10px] font-bold text-rose-200 uppercase tracking-wider">
                                                        {reason.replace('_', ' ')}
                                                    </span>
                                                ))}
                                            </div>
                                        )}

                                        {verificationReportData.robustness_flags && verificationReportData.robustness_flags.length > 0 && (
                                            <div className="flex flex-wrap gap-2">
                                                {verificationReportData.robustness_flags.map((flag) => (
                                                    <span key={flag} className="px-3 py-1 bg-amber-500/10 border border-amber-500/20 rounded-full text-[10px] font-bold text-amber-200 uppercase tracking-wider">
                                                        {flag.replace('_', ' ')}
                                                    </span>
                                                ))}
                                            </div>
                                        )}

                                        {verificationReportData.backtest_summary && (
                                            <div className="bg-slate-950/50 p-5 rounded-xl border border-slate-800 space-y-3">
                                                <div className="text-[9px] font-black text-slate-500 uppercase">Backtest Summary</div>
                                                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-slate-200">
                                                    <div>Win Rate: {verificationReportData.backtest_summary.win_rate ?? 'n/a'}</div>
                                                    <div>Profit Factor: {verificationReportData.backtest_summary.profit_factor ?? 'n/a'}</div>
                                                    <div>Sharpe: {verificationReportData.backtest_summary.sharpe_ratio ?? 'n/a'}</div>
                                                    <div>Max DD: {verificationReportData.backtest_summary.max_drawdown ?? 'n/a'}</div>
                                                    <div>Total Trades: {verificationReportData.backtest_summary.total_trades ?? 'n/a'}</div>
                                                </div>
                                            </div>
                                        )}

                                        {verificationReportData.wfa_summary && (
                                            <div className="bg-slate-950/50 p-5 rounded-xl border border-slate-800 space-y-3">
                                                <div className="text-[9px] font-black text-slate-500 uppercase">Walk-Forward Summary</div>
                                                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-slate-200">
                                                    <div>WFA Sharpe: {verificationReportData.wfa_summary.wfa_sharpe ?? 'n/a'}</div>
                                                    <div>WFE Ratio: {verificationReportData.wfa_summary.wfe_ratio ?? 'n/a'}</div>
                                                    <div>Max DD: {verificationReportData.wfa_summary.wfa_max_drawdown ?? 'n/a'}</div>
                                                    <div>Periods: {verificationReportData.wfa_summary.period_count ?? 'n/a'}</div>
                                                </div>
                                            </div>
                                        )}

                                        {verificationReportData.baseline_gates && Object.keys(verificationReportData.baseline_gates).length > 0 && (
                                            <div className="bg-slate-950/50 p-5 rounded-xl border border-slate-800">
                                                <div className="text-[9px] font-black text-slate-500 uppercase mb-3">Baseline Gates</div>
                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs text-slate-200">
                                                    {Object.entries(verificationReportData.baseline_gates).map(([key, value]) => (
                                                        <div key={key} className="flex items-center justify-between bg-slate-900/60 border border-slate-800 rounded-lg px-3 py-2">
                                                            <span className="font-bold uppercase text-[9px] text-slate-500">{formatLabel(key)}</span>
                                                            <span>{typeof value === 'boolean' ? (value ? 'PASS' : 'FAIL') : String(value)}</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                    </>
                                )}
                            </div>
                        )}
                    </section>
                )}

                <section className="tech-card p-6 shadow-inner bg-slate-900/40">
                    <div className="flex items-center gap-2 mb-6">
                        <Layers size={16} className="text-purple-400" />
                        <span className="text-xs font-black text-white uppercase tracking-[0.2em]">Artifact References</span>
                    </div>
                    {artifactEntries.length > 0 ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {artifactEntries.map(([key, value]) => (
                                <div key={key} className="bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                                    <div className="text-[9px] font-black text-slate-500 uppercase mb-1">
                                        {formatArtifactLabel(key)} ID
                                    </div>
                                    <div className="text-sm font-mono font-bold text-slate-100">{formatArtifactId(value)}</div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="text-xs text-slate-500">No linked artifacts available.</div>
                    )}
                </section>
            </section>
        </div >
    );
};

export const TechnicalAnalysisOutput = memo(TechnicalAnalysisOutputComponent);
