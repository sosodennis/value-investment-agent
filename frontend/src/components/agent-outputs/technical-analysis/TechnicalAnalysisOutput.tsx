import React, { useState, useMemo, memo, useRef } from 'react';
import { AgentStatus, ArtifactReference } from '@/types/agents';
import {
    Activity,
    TrendingUp,
    TrendingDown,
    BrainCircuit,
    LineChart,
    Layers,
    Zap,
    AlertTriangle,
    Bell,
    Sparkles
} from 'lucide-react';
import {
    parseTechnicalArtifact,
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
import { useArtifact } from '../../../hooks/useArtifact';
import { AgentLoadingState } from '../shared/AgentLoadingState';
import { TechnicalAnalysisSupplementarySection } from './TechnicalAnalysisSupplementarySection';
import { TechnicalPreview, isRecord } from '@/types/preview';
import {
    TechnicalCandlestickChart,
    CandlestickDatum,
    VolumeDatum,
    OverlayLineSeries
} from './charts/TechnicalCandlestickChart';
import {
    TechnicalIndicatorChart,
    IndicatorLineSeries,
    IndicatorHistogramSeries,
    IndicatorPriceLine
} from './charts/TechnicalIndicatorChart';
import { useCrosshairSync } from './charts/useCrosshairSync';
import {
    buildMomentumSummaryLine,
    describeIndicatorHighlight,
    formatAlertLifecycleLabel,
    formatAlertQualityGateLabel,
    getQualityStatusDescriptor,
    getSetupReliabilityDescriptor,
    getSignalStrengthDescriptor,
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

type PriceTimeframe = '1d' | '1wk' | '1h';

const PRICE_TIMEFRAME_PREFERENCE: ReadonlyArray<PriceTimeframe> = ['1d', '1wk', '1h'];
const PRICE_TIMEFRAME_SET = new Set<string>(PRICE_TIMEFRAME_PREFERENCE);
const isPriceTimeframe = (value: string): value is PriceTimeframe =>
    PRICE_TIMEFRAME_SET.has(value);

const ALERT_SEVERITY_VALUES: AlertSeverity[] = ['critical', 'warning', 'info'];
const ALERT_SEVERITY_SET = new Set<string>(ALERT_SEVERITY_VALUES);
const isAlertSeverity = (value: string): value is AlertSeverity =>
    ALERT_SEVERITY_SET.has(value);

const LARGE_ARTIFACT_CACHE_MS = 5 * 60 * 1000;
const ALERT_SEVERITY_ORDER: Record<AlertSeverity, number> = {
    critical: 0,
    warning: 1,
    info: 2,
};
const CHART_PANE_HEIGHTS: Record<'price' | 'volume' | 'rsi' | 'macd' | 'fracdiff', number> = {
    price: 260,
    volume: 90,
    rsi: 100,
    macd: 110,
    fracdiff: 90,
};

// --- 1. Semantic Helpers ---

const formatLabel = (value: string) =>
    value
        .split('_')
        .map((part) =>
            part ? `${part.charAt(0).toUpperCase()}${part.slice(1).toLowerCase()}` : ''
        )
        .join(' ')
        .trim();

type DirectionIconKey = 'bull' | 'bear' | 'neutral';

const DIRECTION_ICON_MAP: Record<DirectionIconKey, typeof Activity> = {
    bull: TrendingUp,
    bear: TrendingDown,
    neutral: Activity,
};

const getDirectionIconKey = (direction: string): DirectionIconKey => {
    const normalized = direction.toLowerCase();
    if (normalized.includes('bull') || normalized.includes('up')) return 'bull';
    if (normalized.includes('bear') || normalized.includes('down')) return 'bear';
    return 'neutral';
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
                badge: 'bg-surface-container-high border-outline-variant/30 text-on-surface-variant',
                text: 'text-on-surface-variant',
            };
    }
};

const getLifecycleTone = (state?: string | null) => {
    const normalized = (state ?? '').toLowerCase();
    if (normalized === 'active') {
        return 'bg-emerald-500/15 border-emerald-500/35 text-emerald-200';
    }
    if (normalized === 'monitoring') {
        return 'bg-amber-500/15 border-amber-500/35 text-amber-200';
    }
    if (normalized === 'suppressed') {
        return 'bg-surface-container-high border-outline-variant/30 text-on-surface-variant';
    }
    return 'bg-surface-container-high border-outline-variant/30 text-on-surface-variant';
};

const getQualityGateTone = (gate?: string | null) => {
    const normalized = (gate ?? '').toLowerCase();
    if (normalized === 'passed') {
        return 'bg-emerald-500/15 border-emerald-500/35 text-emerald-200';
    }
    if (normalized === 'degraded') {
        return 'bg-amber-500/15 border-amber-500/35 text-amber-200';
    }
    if (normalized === 'failed') {
        return 'bg-rose-500/15 border-rose-500/35 text-rose-200';
    }
    return 'bg-surface-container-high border-outline-variant/30 text-on-surface-variant';
};

const getIndicatorToneClasses = (tone: IndicatorTone) => {
    if (tone === 'positive') {
        return {
            border: 'border-emerald-500/30',
            bg: 'bg-emerald-500/10',
            value: 'text-emerald-200',
            detail: 'text-emerald-100/80',
        };
    }
    if (tone === 'warning') {
        return {
            border: 'border-amber-500/30',
            bg: 'bg-amber-500/10',
            value: 'text-amber-200',
            detail: 'text-amber-100/80',
        };
    }
    if (tone === 'danger') {
        return {
            border: 'border-rose-500/30',
            bg: 'bg-rose-500/10',
            value: 'text-rose-200',
            detail: 'text-rose-100/80',
        };
    }
    return {
        border: 'border-outline-variant/50',
        bg: 'bg-surface-container-low',
        value: 'text-on-surface',
        detail: 'text-on-surface-variant',
    };
};

const formatConfidence = (value: number | null | undefined) => {
    if (value === undefined || value === null || Number.isNaN(value)) return 'N/A';
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
        badge: 'bg-surface-container-high border-outline-variant/30 text-on-surface-variant',
        value: 'text-on-surface-variant',
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
const coalesceNumber = (...values: Array<number | null | undefined>) =>
    values.find((value) => typeof value === 'number');
const isUtcTimestamp = (value: number): value is CandlestickDatum['time'] =>
    Number.isFinite(value);
const toEpochSeconds = (value: string): CandlestickDatum['time'] | null => {
    const seconds = Math.floor(new Date(value).getTime() / 1000);
    return isUtcTimestamp(seconds) ? seconds : null;
};
const buildIndicatorSeries = (
    series?: Record<string, number | null>
): Array<{ time: CandlestickDatum['time']; value: number }> => {
    const entries = Object.entries(series ?? {})
        .map(([timestamp, value]) => ({
            time: toEpochSeconds(timestamp),
            value,
        }))
        .filter(
            (point): point is { time: CandlestickDatum['time']; value: number } =>
                typeof point.value === 'number' &&
                Number.isFinite(point.value) &&
                point.time !== null
        )
        .sort((a, b) => a.time - b.time)
        .map((point) => ({
            time: point.time,
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
): { time: EpochTime | null; value: V | null } => {
    const nearest = findNearestTime(index.times, target);
    if (nearest === null) return { time: null, value: null };
    return { time: nearest, value: index.map.get(nearest) ?? null };
};

const renderIndicatorHighlights = (indicators: TechnicalFeaturePack['timeframes'][string]['classic_indicators'][string][]) => {
    if (indicators.length === 0) {
        return <span className="text-xs text-outline">No indicators available.</span>;
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
                        className="px-2.5 py-1 bg-surface-container border border-outline-variant/20 rounded-full text-[10px] font-bold text-on-surface uppercase tracking-wide"
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
        return <div className="text-[10px] text-outline">No contributions.</div>;
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
                            : 'text-on-surface-variant';
                return (
                    <div
                        key={`${item.name}-${idx}`}
                        className="flex items-center justify-between gap-3 text-[11px]"
                    >
                        <div>
                            <div className="text-on-surface font-semibold">
                                {formatLabel(item.name)}
                            </div>
                            <div className="text-[10px] text-outline">
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

// --- 2. Main Component ---

const TechnicalAnalysisOutputComponent: React.FC<TechnicalAnalysisOutputProps> = ({
    reference,
    previewData,
    status
}) => {
    const [showFeaturePack, setShowFeaturePack] = useState(false);
    const [showPatternPack, setShowPatternPack] = useState(false);
    const [showAlerts, setShowAlerts] = useState(false);
    const [showFusionReport, setShowFusionReport] = useState(false);
    const [showVerificationReport, setShowVerificationReport] = useState(false);
    const [priceTimeframe, setPriceTimeframe] = useState<string | null>(null);
    const crosshairSync = useCrosshairSync();
    const sectionHeaderTextClass = 'text-[10px] font-bold text-outline uppercase tracking-[0.2em]';

    const { data: reportData } = useArtifact(
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

    const availableTimeseriesFrames = useMemo(() => {
        if (!timeseriesBundleData) return [];
        const frames = Object.keys(timeseriesBundleData.frames);
        return frames.sort((a, b) => {
            const indexA = isPriceTimeframe(a)
                ? PRICE_TIMEFRAME_PREFERENCE.indexOf(a)
                : Number.MAX_SAFE_INTEGER;
            const indexB = isPriceTimeframe(b)
                ? PRICE_TIMEFRAME_PREFERENCE.indexOf(b)
                : Number.MAX_SAFE_INTEGER;
            if (indexA !== indexB) return indexA - indexB;
            return a.localeCompare(b);
        });
    }, [timeseriesBundleData]);

    const preferredTimeseriesFrame = useMemo(() => {
        if (availableTimeseriesFrames.length === 0) return null;
        const preferred =
            availableTimeseriesFrames.find((frame) =>
                isPriceTimeframe(frame)
            ) ?? availableTimeseriesFrames[0];
        return preferred ?? null;
    }, [availableTimeseriesFrames]);

    const resolvedTimeframe =
        priceTimeframe && availableTimeseriesFrames.includes(priceTimeframe)
            ? priceTimeframe
            : preferredTimeseriesFrame;

    const selectedTimeseriesFrame = resolvedTimeframe && timeseriesBundleData
        ? timeseriesBundleData.frames[resolvedTimeframe]
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
            const time = toEpochSeconds(timestamp);
            if (time === null) {
                return;
            }
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
    const isIntradayTimeseries = resolvedTimeframe?.includes('h') ?? false;

    const indicatorTimeframe = useMemo(() => {
        if (!indicatorSeriesData) return null;
        if (resolvedTimeframe && indicatorSeriesData.timeframes[resolvedTimeframe]) {
            return resolvedTimeframe;
        }
        const frames = Object.keys(indicatorSeriesData.timeframes);
        return frames.length > 0 ? frames[0] : null;
    }, [indicatorSeriesData, resolvedTimeframe]);

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
                (point): point is { time: CandlestickDatum['time']; value: number } =>
                    typeof point.value === 'number' &&
                    Number.isFinite(point.value) &&
                    point.time !== null
            )
            .sort((a, b) => a.time - b.time)
            .map((point) => ({
                time: point.time,
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

    const visibleIndicators = indicatorAvailability;
    const hasEvidenceIndicators =
        visibleIndicators.rsi || visibleIndicators.macd || visibleIndicators.fd;

    const bottomTimeScalePane = useMemo(() => {
        if (indicatorAvailability.fd) return 'fd';
        if (indicatorAvailability.macd) return 'macd';
        if (indicatorAvailability.rsi) return 'rsi';
        if (volumeHistogram.length > 0) return 'volume';
        return 'price';
    }, [indicatorAvailability, volumeHistogram.length]);

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
    const chartStackRef = useRef<HTMLDivElement | null>(null);

    const tooltipPayload = useMemo(() => {
        if (!crosshairSync.crosshairTime) return null;
        const anchorTime = crosshairSync.crosshairTime;
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

    const tooltipPosition = useMemo(() => {
        if (!crosshairSync.crosshairPoint || !chartStackRef.current) {
            return null;
        }
        const bounds = chartStackRef.current.getBoundingClientRect();
        const TOOLTIP_WIDTH = 240;
        const TOOLTIP_HEIGHT = 190;
        const padding = 12;
        const localX = crosshairSync.crosshairPoint.x - bounds.left;
        const localY = crosshairSync.crosshairPoint.y - bounds.top;
        const maxX = Math.max(padding, bounds.width - TOOLTIP_WIDTH - padding);
        const maxY = Math.max(padding, bounds.height - TOOLTIP_HEIGHT - padding);
        return {
            x: Math.min(Math.max(localX + padding, padding), maxX),
            y: Math.min(Math.max(localY + padding, padding), maxY),
        };
    }, [crosshairSync.crosshairPoint]);

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
                if (isAlertSeverity(alert.severity)) {
                    acc[alert.severity] += 1;
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
                (isAlertSeverity(a.severity) ? ALERT_SEVERITY_ORDER[a.severity] : 99) -
                (isAlertSeverity(b.severity) ? ALERT_SEVERITY_ORDER[b.severity] : 99);
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
            if (!isPriceTimeframe(frame)) return 99;
            return PRICE_TIMEFRAME_PREFERENCE.indexOf(frame);
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
            const points = typeof meta?.source_points === 'number' ? meta.source_points : 0;
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
                title="Processing Statistical Framework…"
                description="Initializing Analysis Module and computing fractal differences."
                status={status}
                colorClass="text-cyan-400"
            />
        );
    }

    if (!reportData && previewData?.signal_display) {
        return (
            <div className="space-y-6 animate-fade-slide-up">
                <div className="flex items-center justify-between mb-6 px-2">
                    <div className="flex items-center gap-3">
                        <LineChart size={18} className="text-cyan-400" />
                        <h3 className="text-xs font-bold text-outline uppercase tracking-[0.2em]">Technical Intelligence</h3>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="rounded border border-outline-variant/10 bg-surface-container-low px-2 py-1 text-[11px] font-semibold text-primary-container">
                            Preview
                        </span>
                        <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-outline">
                            {previewData?.ticker || 'UNKNOWN'}
                        </span>
                    </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="bg-surface-container p-5 rounded-xl border border-outline-variant/10 text-center transition-colors hover:border-primary-container/30">
                        <div className="text-[10px] font-bold text-outline uppercase tracking-[0.2em] mb-2">Signal</div>
                        <div className="text-lg font-black text-on-surface">{previewData.signal_display}</div>
                    </div>
                    <div className="bg-surface-container p-5 rounded-xl border border-outline-variant/10 text-center transition-colors hover:border-primary-container/30">
                        <div className="text-[10px] font-bold text-outline uppercase tracking-[0.2em] mb-2">Price</div>
                        <div className="text-lg font-black text-on-surface">{previewData.latest_price_display}</div>
                    </div>
                    <div className="bg-surface-container p-5 rounded-xl border border-outline-variant/10 text-center transition-colors hover:border-primary-container/30">
                        <div className="text-[10px] font-bold text-outline uppercase tracking-[0.2em] mb-2">Z-Score</div>
                        <div className="text-lg font-black text-on-surface">{previewData.z_score_display}</div>
                    </div>
                    <div className="bg-surface-container p-5 rounded-xl border border-outline-variant/10 text-center transition-colors hover:border-primary-container/30">
                        <div className="text-[10px] font-bold text-outline uppercase tracking-[0.2em] mb-2">Opt. d</div>
                        <div className="text-lg font-black text-on-surface">{previewData.optimal_d_display}</div>
                    </div>
                </div>

                <AgentLoadingState
                    type="block"
                    title="Loading Full Statistical Analysis…"
                    colorClass="text-cyan-400"
                />
            </div>
        );
    }

    if (!reportData) {
        return (
            <AgentLoadingState
                type="full"
                title="Loading Technical Report…"
                colorClass="text-cyan-400"
                status={status}
            />
        );
    }

    const directionIconKey = getDirectionIconKey(reportData.direction);
    const DirectionIcon = DIRECTION_ICON_MAP[directionIconKey];
    const riskTone = getRiskTone(reportData.risk_level);
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
    const evidenceBundle = reportData.evidence_bundle;
    const qualitySummary = reportData.quality_summary;
    const alertReadout = reportData.alert_readout;
    const observabilitySummary = reportData.observability_summary;
    const signalStrengthSummary = reportData.signal_strength_summary;
    const setupReliabilitySummary = reportData.setup_reliability_summary;
    const signalStrengthDescriptor = getSignalStrengthDescriptor(signalStrengthSummary);
    const setupReliabilityDescriptor =
        getSetupReliabilityDescriptor(setupReliabilitySummary);
    const signalStrengthTone = getIndicatorToneClasses(signalStrengthDescriptor.tone);
    const setupReliabilityTone = getIndicatorToneClasses(setupReliabilityDescriptor.tone);
    const evidenceRegimeSummary = evidenceBundle?.regime_summary;
    const evidenceStructureSummary =
        evidenceBundle?.structure_confluence_summary;
    const evidenceVolumeProfile =
        evidenceBundle?.volume_profile_summary;
    const evidencePoc = coalesceNumber(
        evidenceVolumeProfile?.poc,
        evidenceStructureSummary?.poc
    );
    const evidenceVal = coalesceNumber(
        evidenceVolumeProfile?.val,
        evidenceStructureSummary?.val
    );
    const evidenceVah = coalesceNumber(
        evidenceVolumeProfile?.vah,
        evidenceStructureSummary?.vah
    );
    const evidencePrimaryTimeframe =
        evidenceBundle?.primary_timeframe ?? null;
    const evidenceSupportLevels = evidenceBundle?.support_levels?.slice(0, 2) ?? [];
    const evidenceResistanceLevels =
        evidenceBundle?.resistance_levels?.slice(0, 2) ?? [];
    const evidenceBreakoutSignals = evidenceBundle?.breakout_signals ?? [];
    const evidenceConflictReasons = evidenceBundle?.conflict_reasons ?? [];
    const evidenceScorecard = evidenceBundle?.scorecard_summary;
    const evidenceQuantContext = evidenceBundle?.quant_context_summary;
    const qualityDescriptor = getQualityStatusDescriptor(
        qualitySummary?.is_degraded ?? isDegraded,
        qualitySummary?.overall_quality
    );
    const qualityReadyTimeframes = qualitySummary?.ready_timeframes ?? [];
    const qualityDegradedTimeframes = qualitySummary?.degraded_timeframes ?? [];
    const qualityRegimeReadyTimeframes =
        qualitySummary?.regime_inputs_ready_timeframes ?? [];
    const qualityAlertGateEntries = Object.entries(
        qualitySummary?.alert_quality_gate_counts ?? {}
    );
    const alertTopItems = alertReadout?.top_alerts ?? [];
    const alertReadoutGateEntries = Object.entries(
        alertReadout?.quality_gate_counts ?? {}
    );
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
        <div className="space-y-6 animate-fade-slide-up">
            <div className="flex items-center justify-between mb-6 px-2">
                <div className="flex items-center gap-3">
                    <LineChart size={18} className="text-cyan-400" />
                    <h3 className="text-xs font-bold text-outline uppercase tracking-[0.2em]">Technical Intelligence</h3>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded border border-outline-variant/10 bg-surface-container-low px-2 py-1 text-[11px] font-semibold text-cyan-300">
                        {reportData.ticker}
                    </span>
                    <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-outline">
                        {formatLabel(reportData.schema_version)}
                    </span>
                    <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-outline">
                        As of {reportData.as_of}
                    </span>
                </div>
            </div>

            <section className="space-y-4">
                <div className="flex items-center gap-2">
                    <Activity size={14} className="text-cyan-400 opacity-70" />
                    <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">Overview</span>
                </div>

                <section className="grid grid-cols-1 md:grid-cols-4 gap-4">
                    <div className="rounded-xl bg-surface-container p-5 border border-outline-variant/10 flex flex-col transition-colors hover:border-primary-container/30">
                        <div className="flex-1">
                            <div className="flex justify-between items-start">
                                <div>
                                    <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-outline">Direction</div>
                                    <div className="text-lg font-black text-on-surface mt-1 leading-tight">{formatLabel(reportData.direction)}</div>
                                </div>
                                <div className="p-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/20 shrink-0">
                                    <DirectionIcon size={16} className="text-cyan-400" />
                                </div>
                            </div>
                        </div>
                        <div className="mt-auto pt-4 border-t border-outline-variant/30">
                            <div className="text-[10px] leading-snug text-outline">
                                Primary trend vector based on momentum consensus.
                            </div>
                        </div>
                    </div>
                    <div className={`rounded-xl p-5 flex flex-col border ${riskTone.border} ${riskTone.bg}`}>
                        <div className="flex-1">
                            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-outline">Risk Level</div>
                            <div className={`text-lg font-black mt-1 leading-tight ${riskTone.color}`}>{riskTone.label}</div>
                            {isDegraded && (
                                <div className="text-[9px] uppercase tracking-[0.2em] text-rose-300 mt-2 font-bold">
                                    System Warning
                                </div>
                            )}
                        </div>
                        <div className={`mt-auto pt-4 border-t ${isDegraded ? 'border-rose-500/20' : 'border-outline-variant/30'}`}>
                            <div className={`text-[10px] leading-snug ${isDegraded ? 'text-rose-400' : 'text-outline'}`}>
                                {isDegraded ? 'Degraded Data Path - Use Caution' : 'Composite risk assessment from volatility inputs.'}
                            </div>
                        </div>
                    </div>
                    <div className={`rounded-xl p-5 flex flex-col border ${setupReliabilityTone.border} ${setupReliabilityTone.bg}`}>
                        <div className="flex-1">
                            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-outline">Setup Reliability</div>
                            <div className={`text-lg font-black mt-1 leading-tight ${setupReliabilityTone.value}`}>
                                {setupReliabilityDescriptor.label}
                            </div>
                            <div className={`text-[9px] uppercase tracking-[0.2em] mt-2 ${setupReliabilityTone.detail}`}>
                                {setupReliabilityDescriptor.detail}
                            </div>
                        </div>
                        <div className="mt-auto pt-4 border-t border-outline-variant/30">
                            <div className="text-[10px] leading-snug text-on-surface-variant/80">
                                {setupReliabilityDescriptor.helper}
                            </div>
                        </div>
                    </div>
                    <div className={`rounded-xl p-5 flex flex-col border ${signalStrengthTone.border} ${signalStrengthTone.bg}`}>
                        <div className="flex-1">
                            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-outline">Signal Strength</div>
                            <div className={`text-lg font-black mt-1 leading-tight ${signalStrengthTone.value}`}>
                                {signalStrengthDescriptor.label}
                            </div>
                            <div className={`text-[9px] uppercase tracking-[0.2em] mt-2 ${signalStrengthTone.detail}`}>
                                {signalStrengthDescriptor.detail}
                            </div>
                        </div>
                        <div className="mt-auto pt-4 border-t border-outline-variant/30">
                            <div className="text-[10px] leading-snug text-on-surface-variant/80">
                                {signalStrengthDescriptor.helper}
                            </div>
                        </div>
                    </div>
                </section>

                {momentumSummary && (
                    <div className="flex flex-wrap items-center gap-2 text-xs text-on-surface-variant">
                        <span className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.2em] text-outline">
                            <Zap size={12} className="text-amber-300" />
                            Momentum & Extremes
                        </span>
                        {momentumTimeframe && (
                            <span className="text-[9px] text-outline uppercase">
                                {momentumTimeframe.toUpperCase()}
                            </span>
                        )}
                        <span className="text-on-surface-variant">{momentumSummary}</span>
                    </div>
                )}

                {(evidenceBundle || reportData.regime_summary || reportData.structure_confluence_summary) && (
                    <section className="space-y-4">
                        <div className="flex items-center gap-2">
                            <Sparkles size={14} className="text-cyan-300 opacity-70" />
                            <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">
                                Key Evidence
                            </span>
                            {evidencePrimaryTimeframe && (
                                <span className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                    {evidencePrimaryTimeframe.toUpperCase()}
                                </span>
                            )}
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
                            <div className="rounded-xl border border-outline-variant/10 bg-surface-container p-5 space-y-3">
                                <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                    Regime & Score
                                </div>
                                <div className="text-lg font-black text-on-surface">
                                    {evidenceRegimeSummary?.dominant_regime
                                        ? formatLabel(evidenceRegimeSummary.dominant_regime)
                                        : 'No regime readout'}
                                </div>
                                <div className="space-y-1 text-[11px] text-on-surface-variant">
                                    {typeof evidenceRegimeSummary?.average_confidence === 'number' && (
                                        <div>
                                            Regime confidence: {formatConfidence(evidenceRegimeSummary.average_confidence)}
                                        </div>
                                    )}
                                    {typeof evidenceScorecard?.overall_score === 'number' && (
                                        <div>
                                            Overall evidence score: {formatConfidence(evidenceScorecard.overall_score)}
                                        </div>
                                    )}
                                    {evidenceScorecard?.classic_label && (
                                        <div>
                                            Classic readout: {formatLabel(evidenceScorecard.classic_label)}
                                        </div>
                                    )}
                                    {evidenceScorecard?.quant_label && (
                                        <div>
                                            Quant readout: {formatLabel(evidenceScorecard.quant_label)}
                                        </div>
                                    )}
                                </div>
                            </div>

                            <div className="rounded-xl border border-outline-variant/10 bg-surface-container p-5 space-y-3">
                                <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                    Structure Map
                                </div>
                                <div className="text-lg font-black text-on-surface">
                                    {evidenceStructureSummary?.confluence_state
                                        ? formatLabel(evidenceStructureSummary.confluence_state)
                                        : 'Structure readout pending'}
                                </div>
                                <div className="space-y-2 text-[11px] text-on-surface-variant">
                                    {typeof evidenceStructureSummary?.confluence_score === 'number' && (
                                        <div>
                                            Confluence score: {formatConfidence(evidenceStructureSummary.confluence_score)}
                                        </div>
                                    )}
                                    {typeof evidencePoc === 'number' && (
                                        <div>
                                            POC: {formatPrice(evidencePoc)}
                                        </div>
                                    )}
                                    {typeof evidenceVal === 'number' &&
                                        typeof evidenceVah === 'number' && (
                                            <div>
                                                Value area: {formatPrice(evidenceVal)} - {formatPrice(evidenceVah)}
                                            </div>
                                        )}
                                    {evidenceSupportLevels.length > 0 && (
                                        <div>
                                            Support: {evidenceSupportLevels.map((level) => formatPrice(level)).join(' / ')}
                                        </div>
                                    )}
                                    {evidenceResistanceLevels.length > 0 && (
                                        <div>
                                            Resistance: {evidenceResistanceLevels.map((level) => formatPrice(level)).join(' / ')}
                                        </div>
                                    )}
                                </div>
                            </div>

                            <div className="rounded-xl border border-outline-variant/10 bg-surface-container p-5 space-y-3">
                                <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                    Breakouts & Tensions
                                </div>
                                <div className="flex flex-wrap gap-2">
                                    {evidenceBreakoutSignals.length > 0 ? (
                                        evidenceBreakoutSignals.slice(0, 3).map((signal) => (
                                            <span
                                                key={`${signal.name}-${signal.confidence ?? 'na'}`}
                                                className="px-2.5 py-1 rounded-full border border-cyan-500/25 bg-cyan-500/10 text-[10px] font-bold uppercase tracking-wide text-cyan-200"
                                            >
                                                {formatLabel(signal.name)}
                                            </span>
                                        ))
                                    ) : (
                                        <span className="text-xs text-outline">
                                            No breakout signal in the primary bundle.
                                        </span>
                                    )}
                                </div>
                                <div className="space-y-2 text-[11px] text-on-surface-variant">
                                    {evidenceConflictReasons.length > 0 ? (
                                        <>
                                            <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                                Conflict Reasons
                                            </div>
                                            <div className="flex flex-wrap gap-2">
                                                {evidenceConflictReasons.slice(0, 3).map((reason) => (
                                                    <span
                                                        key={reason}
                                                        className="px-2.5 py-1 rounded-full border border-amber-500/20 bg-amber-500/10 text-[10px] font-bold uppercase tracking-wide text-amber-200"
                                                    >
                                                        {formatLabel(reason)}
                                                    </span>
                                                ))}
                                            </div>
                                        </>
                                    ) : (
                                        <div>No major evidence conflict is flagged in the report bundle.</div>
                                    )}
                                </div>
                            </div>

                            {evidenceQuantContext && (
                                <div className="rounded-xl border border-outline-variant/10 bg-surface-container p-5 space-y-3">
                                    <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                        Quant Context
                                    </div>
                                    <div className="text-lg font-black text-on-surface">
                                        {evidenceQuantContext.alignment_state
                                            ? formatLabel(evidenceQuantContext.alignment_state)
                                            : evidenceQuantContext.stretch_state
                                                ? formatLabel(evidenceQuantContext.stretch_state)
                                                : 'Quant context pending'}
                                    </div>
                                    <div className="space-y-1 text-[11px] text-on-surface-variant">
                                        {evidenceQuantContext.volatility_regime && (
                                            <div>
                                                Volatility: {formatLabel(evidenceQuantContext.volatility_regime)}
                                            </div>
                                        )}
                                        {evidenceQuantContext.liquidity_regime && (
                                            <div>
                                                Liquidity: {formatLabel(evidenceQuantContext.liquidity_regime)}
                                            </div>
                                        )}
                                        {evidenceQuantContext.stretch_state && (
                                            <div>
                                                Stretch: {formatLabel(evidenceQuantContext.stretch_state)}
                                            </div>
                                        )}
                                        {typeof evidenceQuantContext.price_vs_sma20_z === 'number' && (
                                            <div>
                                                Price/SMA Z:{' '}
                                                {`${evidenceQuantContext.price_vs_sma20_z >= 0 ? '+' : ''}${evidenceQuantContext.price_vs_sma20_z.toFixed(2)}`}
                                            </div>
                                        )}
                                        {typeof evidenceQuantContext.alignment_ratio === 'number' && (
                                            <div>
                                                Alignment ratio: {formatConfidence(evidenceQuantContext.alignment_ratio)}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    </section>
                )}

                {(qualitySummary || isDegraded || degradedReasons.length > 0) && (
                    <section className="space-y-4">
                        <div className="flex items-center gap-2">
                            <AlertTriangle size={14} className="text-amber-300 opacity-70" />
                            <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">
                                Quality & Coverage
                            </span>
                        </div>
                        <div className="rounded-xl border border-outline-variant/10 bg-surface-container p-5 space-y-4">
                            <div className="flex flex-wrap items-start justify-between gap-4">
                                <div>
                                    <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                        Coverage Status
                                    </div>
                                    <div className="mt-2 text-lg font-black text-on-surface">
                                        {qualityDescriptor.label}
                                    </div>
                                    <p className="mt-2 max-w-2xl text-[12px] leading-6 text-on-surface-variant">
                                        {qualityDescriptor.meaning}
                                    </p>
                                </div>
                                <span
                                    className={`inline-flex px-3 py-1 rounded-full border text-[10px] font-black uppercase tracking-[0.2em] ${tonePalette[qualityDescriptor.tone].badge}`}
                                >
                                    {qualitySummary?.overall_quality
                                        ? formatLabel(qualitySummary.overall_quality)
                                        : 'Unrated'}
                                </span>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                                <div className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-4">
                                    <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                        Ready Frames
                                    </div>
                                    <div className="mt-2 text-lg font-black text-on-surface">
                                        {qualityReadyTimeframes.length}
                                    </div>
                                    <div className="mt-2 text-[10px] text-on-surface-variant">
                                        {qualityReadyTimeframes.length > 0
                                            ? qualityReadyTimeframes.map((frame) => frame.toUpperCase()).join(' · ')
                                            : 'None reported'}
                                    </div>
                                </div>
                                <div className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-4">
                                    <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                        Degraded Frames
                                    </div>
                                    <div className="mt-2 text-lg font-black text-on-surface">
                                        {qualityDegradedTimeframes.length}
                                    </div>
                                    <div className="mt-2 text-[10px] text-on-surface-variant">
                                        {qualityDegradedTimeframes.length > 0
                                            ? qualityDegradedTimeframes.map((frame) => frame.toUpperCase()).join(' · ')
                                            : 'No degraded frame listed'}
                                    </div>
                                </div>
                                <div className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-4">
                                    <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                        Regime Inputs Ready
                                    </div>
                                    <div className="mt-2 text-lg font-black text-on-surface">
                                        {qualityRegimeReadyTimeframes.length}
                                    </div>
                                    <div className="mt-2 text-[10px] text-on-surface-variant">
                                        {qualityRegimeReadyTimeframes.length > 0
                                            ? qualityRegimeReadyTimeframes.map((frame) => frame.toUpperCase()).join(' · ')
                                            : 'No regime-ready frame listed'}
                                    </div>
                                </div>
                                <div className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-4">
                                    <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                        Unavailable Indicators
                                    </div>
                                    <div className="mt-2 text-lg font-black text-on-surface">
                                        {qualitySummary?.unavailable_indicator_count ?? 0}
                                    </div>
                                    <div className="mt-2 text-[10px] text-on-surface-variant">
                                        Count reflects missing or intentionally skipped inputs.
                                    </div>
                                </div>
                            </div>
                            {(qualityAlertGateEntries.length > 0 || degradedReasons.length > 0) && (
                                <div className="space-y-2">
                                    {qualityAlertGateEntries.length > 0 && (
                                        <div className="flex flex-wrap gap-2">
                                            {qualityAlertGateEntries.map(([gate, count]) => (
                                                <span
                                                    key={gate}
                                                    className={`px-2.5 py-1 rounded-full border text-[10px] font-bold uppercase tracking-wide ${getQualityGateTone(gate)}`}
                                                >
                                                    {formatAlertQualityGateLabel(gate)} · {count}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                    {degradedReasons.length > 0 && (
                                        <div className="flex flex-wrap gap-2">
                                            {degradedReasons.slice(0, 4).map((reason) => (
                                                <span
                                                    key={reason}
                                                    className="px-2.5 py-1 rounded-full border border-rose-500/20 bg-rose-500/10 text-[10px] font-bold uppercase tracking-wide text-rose-200"
                                                >
                                                    {formatLabel(reason)}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    </section>
                )}

                {alertReadout && (
                    <section className="space-y-4">
                        <div className="flex items-center gap-2">
                            <Bell size={14} className="text-rose-300 opacity-70" />
                            <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">
                                Policy Alerts
                            </span>
                        </div>
                        <div className="rounded-xl border border-outline-variant/10 bg-surface-container p-5 space-y-4">
                            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                                <div className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-4">
                                    <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                        Total Alerts
                                    </div>
                                    <div className="mt-2 text-lg font-black text-on-surface">
                                        {alertReadout.total_alerts ?? 0}
                                    </div>
                                </div>
                                <div className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-4">
                                    <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                        Highest Severity
                                    </div>
                                    <div className="mt-2 text-lg font-black text-on-surface">
                                        {alertReadout.highest_severity
                                            ? formatLabel(alertReadout.highest_severity)
                                            : 'None'}
                                    </div>
                                </div>
                                <div className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-4">
                                    <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                        Active / Monitoring
                                    </div>
                                    <div className="mt-2 text-lg font-black text-on-surface">
                                        {alertReadout.active_alert_count ?? 0} / {alertReadout.monitoring_alert_count ?? 0}
                                    </div>
                                </div>
                                <div className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-4">
                                    <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                        Suppressed
                                    </div>
                                    <div className="mt-2 text-lg font-black text-on-surface">
                                        {alertReadout.suppressed_alert_count ?? 0}
                                    </div>
                                </div>
                            </div>
                            {alertTopItems.length > 0 ? (
                                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                                    {alertTopItems.map((alert) => {
                                        const tone = getAlertSeverityTone(
                                            isAlertSeverity(alert.severity) ? alert.severity : 'info'
                                        );
                                        return (
                                            <div
                                                key={`${alert.code}-${alert.policy_code ?? 'na'}`}
                                                className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-4 space-y-3"
                                            >
                                                <div className="flex items-start justify-between gap-3">
                                                    <div>
                                                        <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                                            {alert.timeframe.toUpperCase()} · {formatLabel(alert.code)}
                                                        </div>
                                                        <div className="mt-2 text-sm font-black text-on-surface">
                                                            {alert.title}
                                                        </div>
                                                    </div>
                                                    <span
                                                        className={`px-2.5 py-1 rounded-full border text-[9px] font-black uppercase tracking-[0.2em] ${tone.badge}`}
                                                    >
                                                        {tone.label}
                                                    </span>
                                                </div>
                                                <div className="flex flex-wrap gap-2">
                                                    {alert.lifecycle_state && (
                                                        <span
                                                            className={`px-2.5 py-1 rounded-full border text-[9px] font-bold uppercase tracking-wide ${getLifecycleTone(alert.lifecycle_state)}`}
                                                        >
                                                            {formatAlertLifecycleLabel(alert.lifecycle_state)}
                                                        </span>
                                                    )}
                                                    {alert.policy_code && (
                                                        <span className="px-2.5 py-1 rounded-full border border-cyan-500/20 bg-cyan-500/10 text-[9px] font-bold uppercase tracking-wide text-cyan-200">
                                                            {formatLabel(alert.policy_code)}
                                                        </span>
                                                    )}
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            ) : (
                                <div className="text-xs text-outline">
                                    No policy alert summary is available for this report.
                                </div>
                            )}
                            {alertReadoutGateEntries.length > 0 && (
                                <div className="flex flex-wrap gap-2">
                                    {alertReadoutGateEntries.map(([gate, count]) => (
                                        <span
                                            key={gate}
                                            className={`px-2.5 py-1 rounded-full border text-[10px] font-bold uppercase tracking-wide ${getQualityGateTone(gate)}`}
                                        >
                                            {formatAlertQualityGateLabel(gate)} · {count}
                                        </span>
                                    ))}
                                </div>
                            )}
                        </div>
                    </section>
                )}

                <section className="relative overflow-hidden rounded-xl border border-outline-variant/10 bg-surface-container p-6 group">
                    <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                        <BrainCircuit size={80} className="text-indigo-400" />
                    </div>
                    <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                        <div className="flex items-center gap-2">
                            <BrainCircuit size={18} className="text-indigo-400" />
                            <span className="text-xs font-black text-indigo-200 uppercase tracking-[0.2em]">Analyst Perspective</span>
                        </div>
                        {analystPerspective?.decision_posture && (
                            <span className="px-3 py-1 rounded-full border border-indigo-400/25 bg-indigo-500/10 text-[10px] font-black uppercase tracking-[0.2em] text-indigo-200">
                                {formatLabel(analystPerspective.decision_posture)}
                            </span>
                        )}
                    </div>
                    {analystPerspective ? (
                        <div className="space-y-5">
                            <div className="flex flex-wrap items-start justify-between gap-4">
                                <div className="space-y-4">
                                    <div className="flex flex-col md:flex-row md:items-start gap-4 mb-2">
                                        <div className="flex-1 text-xl font-black text-on-surface leading-snug">
                                            {analystPerspective.stance_summary}
                                        </div>
                                        <div className="px-3 py-2 rounded-xl border border-indigo-400/30 bg-indigo-500/10 min-w-[160px] shrink-0">
                                            <div className="text-[9px] font-black uppercase tracking-[0.2em] text-indigo-300">Stance</div>
                                            <div className="mt-1 text-sm font-black text-indigo-100">
                                                {formatLabel(analystPerspective.stance)}
                                            </div>
                                        </div>
                                    </div>

                                    <div className="space-y-4 max-w-4xl">
                                        {analystPerspective.plain_language_summary && (
                                            <p className="text-[15px] leading-8 text-indigo-100/90">
                                                {analystPerspective.plain_language_summary}
                                            </p>
                                        )}
                                        <p className="text-[13px] leading-7 text-on-surface-variant">
                                            {analystPerspective.rationale_summary}
                                        </p>
                                    </div>
                                </div>
                            </div>
                            {analystEvidence.length > 0 && (
                                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                    {analystEvidence.map((item) => (
                                        <div
                                            key={`${item.label}-${item.timeframe ?? 'na'}`}
                                            className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-4"
                                        >
                                            <div className="flex items-center justify-between gap-3">
                                                <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-outline">
                                                    {item.label}
                                                </span>
                                                {item.timeframe && (
                                                    <span className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">
                                                        {item.timeframe}
                                                    </span>
                                                )}
                                            </div>
                                            {item.value_text && (
                                                <div className="mt-2 text-lg font-mono font-bold text-indigo-200">
                                                    {item.value_text}
                                                </div>
                                            )}
                                            <p className="mt-2 text-xs leading-6 text-on-surface-variant">
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
                                        <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-outline">
                                            Simple Signal Guide
                                        </span>
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                        {analystSignalExplainers.map((item) => (
                                            <div
                                                key={`${item.signal}-${item.timeframe ?? 'na'}`}
                                                className="relative overflow-hidden flex flex-col justify-between h-full rounded-xl border border-indigo-500/20 bg-indigo-500/[0.03] hover:bg-indigo-500/[0.06] transition-colors p-5"
                                            >
                                                <div className="flex flex-col gap-1 mb-4">
                                                    <div className="flex items-start justify-between gap-3">
                                                        <div className="text-[10px] font-black uppercase tracking-[0.2em] text-indigo-300">
                                                            {item.plain_name}
                                                        </div>
                                                        {item.timeframe && (
                                                            <div className="text-[9px] font-bold uppercase tracking-[0.2em] px-2 py-0.5 rounded border border-indigo-400/20 bg-indigo-500/10 text-indigo-200">
                                                                {item.timeframe}
                                                            </div>
                                                        )}
                                                    </div>

                                                    <div className="flex items-end gap-3 mt-1">
                                                        {item.value_text && (
                                                            <div className="text-xl font-mono font-black text-on-surface">
                                                                {item.value_text}
                                                            </div>
                                                        )}
                                                        <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-outline mb-1">
                                                            {item.signal}
                                                        </div>
                                                    </div>
                                                </div>

                                                <div className="flex flex-col flex-1">
                                                    <p className="text-[13px] leading-6 text-on-surface-variant">
                                                        {item.what_it_means_now}
                                                    </p>

                                                    <div className="mt-auto pt-4 relative">
                                                        <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-indigo-500/20 to-transparent"></div>
                                                        <p className="text-[11px] leading-5 text-on-surface-variant pt-3">
                                                            <span className="font-bold text-outline block mb-1 uppercase tracking-[0.2em] text-[9px]">Why it matters</span>
                                                            {item.why_it_matters_now}
                                                        </p>
                                                    </div>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                <div className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-4">
                                    <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">Trigger</div>
                                    <div className="mt-2 text-sm leading-6 text-on-surface-variant">
                                        {analystPerspective.trigger_condition ?? 'No explicit trigger detected.'}
                                    </div>
                                </div>
                                <div className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-4">
                                    <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">Invalidation</div>
                                    <div className="mt-2 text-sm leading-6 text-on-surface-variant">
                                        {analystPerspective.invalidation_condition ?? 'No explicit invalidation level available.'}
                                    </div>
                                    {analystInvalidationLevel && (
                                        <div className="mt-2 text-[10px] font-black uppercase tracking-[0.2em] text-rose-300">
                                            Level {analystInvalidationLevel}
                                        </div>
                                    )}
                                </div>
                                <div className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-4">
                                    <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">Validation Note</div>
                                    <div className="mt-2 text-sm leading-6 text-on-surface-variant">
                                        {analystPerspective.validation_note ?? 'No validation warning was supplied.'}
                                    </div>
                                </div>
                                <div className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-4">
                                    <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline">Confidence Note</div>
                                    <div className="mt-2 text-sm leading-6 text-on-surface-variant">
                                        {analystPerspective.confidence_note ?? 'Confidence follows the deterministic calibration output.'}
                                    </div>
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="text-base text-on-surface-variant leading-relaxed">
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
                            <span className="text-xs text-outline">No summary tags available.</span>
                        )}
                    </div>
                </section>

            </section>

            {(hasEvidenceIndicators || indicatorSeriesId) && (
                <section className="space-y-4">
                    <div className="flex items-center gap-2">
                        <Zap size={14} className="text-amber-300 opacity-70" />
                        <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">Setup Evidence</span>
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
                                    <div className="flex items-center justify-between text-[10px] font-bold text-outline uppercase">
                                        <span>Momentum & Extremes</span>
                                        {momentumTimeframe && (
                                            <span className="text-[9px] text-outline uppercase">
                                                {momentumTimeframe.toUpperCase()}
                                            </span>
                                        )}
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 flex-1">
                                        {visibleIndicators.rsi && (
                                            <div className="relative overflow-hidden flex flex-col justify-between h-full bg-surface-container border border-outline-variant/20 rounded-xl p-4">
                                                <div className="flex items-start justify-between gap-3 mb-3">
                                                    <div>
                                                        <div className="text-[9px] font-bold text-outline uppercase">RSI (14)</div>
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
                                                        <div className="text-[10px] text-outline uppercase">
                                                            Momentum State
                                                        </div>
                                                        <div className="max-w-[150px] text-[11px] leading-5 text-on-surface-variant flex-1">
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
                                                            <div className="text-[10px] text-outline uppercase">No trend</div>
                                                        )}
                                                    </div>
                                                </div>
                                            </div>
                                        )}
                                        {visibleIndicators.fd && (
                                            <div className="relative overflow-hidden flex flex-col justify-between h-full bg-surface-container border border-outline-variant/20 rounded-xl p-4">
                                                <div className="flex items-start justify-between gap-3 mb-3">
                                                    <div>
                                                        <div className="text-[9px] font-bold text-outline uppercase">FD Z-Score</div>
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
                                                        <div className="text-[10px] text-outline uppercase">
                                                            Deviation State
                                                        </div>
                                                        <div className="max-w-[150px] text-[11px] leading-5 text-on-surface-variant flex-1">
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
                                                            <div className="text-[10px] text-outline uppercase">No trend</div>
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
                                    <div className="flex items-center justify-between text-[10px] font-bold text-outline uppercase">
                                        <span>Trend & Momentum</span>
                                        {momentumTimeframe && (
                                            <span className="text-[9px] text-outline uppercase">
                                                {momentumTimeframe.toUpperCase()}
                                            </span>
                                        )}
                                    </div>
                                    <div className="grid grid-cols-1 gap-4 flex-1">
                                        <div className="relative overflow-hidden flex flex-col justify-between h-full bg-surface-container border border-outline-variant/20 rounded-xl p-4">
                                            <div className="flex items-start justify-between gap-3 mb-3">
                                                <div>
                                                    <div className="text-[9px] font-bold text-outline uppercase">MACD</div>
                                                    <div
                                                        className={`text-xl font-mono font-bold ${tonePalette[macdTone.tone].value} ${tonePalette[macdTone.tone].glow}`}
                                                    >
                                                        {formatIndicatorValue(latestMacd)}
                                                    </div>
                                                    <div className="text-[10px] text-outline uppercase">
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
                                                    <div className="text-[10px] text-outline uppercase">
                                                        Momentum State
                                                    </div>
                                                    <div className="max-w-[150px] text-[11px] leading-5 text-on-surface-variant flex-1">
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
                                                        <div className="text-[10px] text-outline uppercase">No trend</div>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    ) : (
                        <div className="text-xs text-outline">
                            Indicator evidence unavailable for this run.
                        </div>
                    )}
                </section>
            )}

            <section className="space-y-4">
                {timeseriesBundleData && (
                    <div className="bg-surface-container border border-outline-variant/10 rounded-xl p-4">
                        <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
                            <div className="flex items-center gap-2">
                                <Layers size={14} className="text-cyan-400 opacity-50" />
                                <span className={sectionHeaderTextClass}>Multi-pane Chart Stack</span>
                            </div>
                            <div className="flex flex-wrap items-center gap-4">
                                {availableTimeseriesFrames.length > 0 ? (
                                    <div className="flex items-center bg-surface-container-high rounded-lg p-0.5 border border-outline-variant/50">
                                        {availableTimeseriesFrames.map((frame) => (
                                            <button
                                                key={frame}
                                                onClick={() => setPriceTimeframe(frame)}
                                                className={`px-2 py-1 rounded text-[9px] font-bold transition ${resolvedTimeframe === frame
                                                    ? 'bg-cyan-500/20 text-cyan-400 shadow-[0_0_10px_rgba(34,211,238,0.1)]'
                                                    : 'text-outline hover:text-on-surface-variant'
                                                    }`}
                                            >
                                                {frame.toUpperCase()}
                                            </button>
                                        ))}
                                    </div>
                                ) : (
                                    <div className="text-[10px] text-outline uppercase">
                                        No OHLC frames
                                    </div>
                                )}
                                {indicatorTimeframe && (
                                    <div className="text-[10px] font-bold uppercase text-outline">
                                        Indicators: {indicatorTimeframe.toUpperCase()}
                                    </div>
                                )}
                                {timeseriesWindow && (
                                    <div className="text-[10px] font-bold uppercase text-outline">
                                        {timeseriesWindow.start} → {timeseriesWindow.end}
                                    </div>
                                )}
                            </div>
                        </div>

                        <div ref={chartStackRef} className="relative rounded-xl border border-outline-variant/20 bg-surface-container-low">
                            <div className="divide-y divide-outline-variant/20">
                                <div className="px-4 py-3">
                                    <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                                        <div className="text-[9px] font-bold text-outline uppercase">
                                            Price Action (OHLCV)
                                        </div>
                                        {priceOverlays.length > 0 && (
                                            <div className="flex flex-wrap items-center gap-3 text-[9px] text-outline uppercase">
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
                                    <div className="text-[9px] font-bold text-outline uppercase mb-2">Volume</div>
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
                                        <div className="text-xs text-outline">Volume data unavailable.</div>
                                    )}
                                </div>

                                <div className="px-4 py-3">
                                    <div className="text-[9px] font-bold text-outline uppercase mb-2">RSI (14)</div>
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
                                        <div className="text-xs text-outline">RSI data unavailable.</div>
                                    )}
                                </div>

                                <div className="px-4 py-3">
                                    <div className="text-[9px] font-bold text-outline uppercase mb-2">MACD</div>
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
                                        <div className="text-xs text-outline">MACD data unavailable.</div>
                                    )}
                                </div>

                                <div className="px-4 py-3">
                                    <div className="text-[9px] font-bold text-outline uppercase mb-2">FracDiff</div>
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
                                        <div className="text-xs text-outline">Fracdiff data unavailable.</div>
                                    )}
                                </div>
                            </div>

                            {tooltipPosition && tooltipPayload && (
                                <div
                                    className="pointer-events-none absolute z-50 w-60 rounded-xl border border-outline-variant/40 bg-surface-container-highest backdrop-blur-md p-3 text-[10px] text-on-surface shadow-[0_12px_30px_rgba(0,0,0,0.45)]"
                                    style={{ left: tooltipPosition.x, top: tooltipPosition.y }}
                                >
                                    <div className="text-[9px] font-bold uppercase text-outline mb-2">
                                        {formatTooltipTimestamp(tooltipPayload.time, isIntradayTimeseries)}
                                    </div>
                                    <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                                        <div>O: {tooltipPayload.candle ? formatPrice(tooltipPayload.candle.open) : 'n/a'}</div>
                                        <div>H: {tooltipPayload.candle ? formatPrice(tooltipPayload.candle.high) : 'n/a'}</div>
                                        <div>L: {tooltipPayload.candle ? formatPrice(tooltipPayload.candle.low) : 'n/a'}</div>
                                        <div>C: {tooltipPayload.candle ? formatPrice(tooltipPayload.candle.close) : 'n/a'}</div>
                                    </div>
                                    <div className="mt-2 border-t border-outline-variant/30 pt-2 space-y-1">
                                        <div className="flex items-center justify-between">
                                            <span className="text-on-surface-variant">Volume</span>
                                            <span>{formatVolume(tooltipPayload.volume)}</span>
                                        </div>
                                        <div className="flex items-center justify-between">
                                            <span className="text-on-surface-variant">RSI</span>
                                            <span>{formatIndicatorValue(tooltipPayload.rsi)}</span>
                                        </div>
                                        <div className="flex items-center justify-between">
                                            <span className="text-on-surface-variant">MACD</span>
                                            <span>{formatIndicatorValue(tooltipPayload.macd)}</span>
                                        </div>
                                        <div className="flex items-center justify-between">
                                            <span className="text-on-surface-variant">Signal Line</span>
                                            <span>{formatIndicatorValue(tooltipPayload.macdSignal)}</span>
                                        </div>
                                        <div className="flex items-center justify-between">
                                            <span className="text-on-surface-variant">Histogram</span>
                                            <span>{formatIndicatorValue(tooltipPayload.macdHist)}</span>
                                        </div>
                                        <div className="flex items-center justify-between">
                                            <span className="text-on-surface-variant">FracDiff</span>
                                            <span>{formatIndicatorValue(tooltipPayload.fd)}</span>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                        <div className="mt-2 flex justify-end text-[9px] text-outline">
                            <a
                                href="https://www.tradingview.com/"
                                target="_blank"
                                rel="noreferrer"
                                className="hover:text-on-surface-variant underline"
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
                    <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">Diagnostics</span>
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
                    <section className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-5">
                        <div className="flex items-center gap-2 mb-3">
                            <AlertTriangle size={16} className="text-rose-400" />
                            <span className="text-xs font-black text-rose-200 uppercase tracking-[0.2em]">Degraded Data Path</span>
                        </div>
                        <div className="text-xs text-on-surface-variant">
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

                {observabilitySummary && (
                    <div className="bg-surface-container p-4 rounded-xl border border-outline-variant/10">
                        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
                            <div className="text-[9px] font-bold text-outline uppercase tracking-[0.2em]">
                                Observability Summary
                            </div>
                            {observabilitySummary.primary_timeframe && (
                                <div className="text-[10px] font-bold uppercase text-outline">
                                    Primary {observabilitySummary.primary_timeframe.toUpperCase()}
                                </div>
                            )}
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-xs text-on-surface">
                            <div>Loaded Artifacts: {observabilitySummary.loaded_artifact_count ?? 0}</div>
                            <div>Missing Artifacts: {observabilitySummary.missing_artifact_count ?? 0}</div>
                            <div>Degraded Reasons: {observabilitySummary.degraded_reason_count ?? 0}</div>
                            <div>
                                Timeframes:{' '}
                                {observabilitySummary.observed_timeframes?.length
                                    ? observabilitySummary.observed_timeframes
                                        .map((frame) => frame.toUpperCase())
                                        .join(' · ')
                                    : 'n/a'}
                            </div>
                        </div>
                        <div className="mt-3 space-y-2">
                            {observabilitySummary.loaded_artifacts &&
                                observabilitySummary.loaded_artifacts.length > 0 && (
                                    <div className="flex flex-wrap gap-2">
                                        {observabilitySummary.loaded_artifacts.map((artifact) => (
                                            <span
                                                key={`loaded-${artifact}`}
                                                className="px-2.5 py-1 bg-emerald-500/10 border border-emerald-500/20 rounded-full text-[10px] font-bold text-emerald-200 uppercase tracking-wide"
                                            >
                                                Loaded · {formatLabel(artifact)}
                                            </span>
                                        ))}
                                    </div>
                                )}
                            {observabilitySummary.missing_artifacts &&
                                observabilitySummary.missing_artifacts.length > 0 && (
                                    <div className="flex flex-wrap gap-2">
                                        {observabilitySummary.missing_artifacts.map((artifact) => (
                                            <span
                                                key={`missing-${artifact}`}
                                                className="px-2.5 py-1 bg-surface-container-high border border-outline-variant/30 rounded-full text-[10px] font-bold text-on-surface-variant uppercase tracking-wide"
                                            >
                                                Missing · {formatLabel(artifact)}
                                            </span>
                                        ))}
                                    </div>
                                )}
                            {observabilitySummary.degraded_artifacts &&
                                observabilitySummary.degraded_artifacts.length > 0 && (
                                    <div className="flex flex-wrap gap-2">
                                        {observabilitySummary.degraded_artifacts.map((artifact) => (
                                            <span
                                                key={`degraded-${artifact}`}
                                                className="px-2.5 py-1 bg-amber-500/10 border border-amber-500/20 rounded-full text-[10px] font-bold text-amber-200 uppercase tracking-wide"
                                            >
                                                Degraded · {formatLabel(artifact)}
                                            </span>
                                        ))}
                                    </div>
                                )}
                        </div>
                    </div>
                )}

                {timeseriesSummary && (
                    <div className="bg-surface-container p-4 rounded-xl border border-outline-variant/10">
                        <div className="text-[9px] font-bold text-outline uppercase mb-2">OHLC Series</div>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-on-surface">
                            <div>Frames: {timeseriesSummary.frameCount}</div>
                            <div>Max Points: {timeseriesSummary.maxPoints}</div>
                            <div>Selected: {resolvedTimeframe ? resolvedTimeframe.toUpperCase() : 'n/a'}</div>
                        </div>
                        {timeseriesSummary.degradedReasons.length > 0 && (
                            <div className="mt-2 text-[10px] text-amber-300">
                                Degraded: {timeseriesSummary.degradedReasons.join(', ')}
                            </div>
                        )}
                    </div>
                )}

                {indicatorSeriesSummary && (
                    <div className="bg-surface-container p-4 rounded-xl border border-outline-variant/10">
                        <div className="text-[9px] font-bold text-outline uppercase mb-2">Indicator Series</div>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-on-surface">
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
                    <div className="bg-surface-container p-4 rounded-xl border border-outline-variant/10">
                        <div className="text-[9px] font-bold text-outline uppercase mb-2">Raw Momentum & Extremes Data</div>
                        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-xs text-on-surface">
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

            <TechnicalAnalysisSupplementarySection
                alertsId={alertsId}
                alertsData={alertsData}
                alertsSummary={alertsSummary}
                alertsError={alertsError}
                isAlertsLoadingState={isAlertsLoadingState}
                showAlerts={showAlerts}
                setShowAlerts={setShowAlerts}
                featurePackId={featurePackId}
                featurePackData={featurePackData}
                featurePackSummary={featurePackSummary}
                featurePackError={featurePackError}
                isFeaturePackLoading={isFeaturePackLoading}
                showFeaturePack={showFeaturePack}
                setShowFeaturePack={setShowFeaturePack}
                patternPackId={patternPackId}
                patternPackData={patternPackData}
                patternPackSummary={patternPackSummary}
                patternPackError={patternPackError}
                isPatternPackLoading={isPatternPackLoading}
                showPatternPack={showPatternPack}
                setShowPatternPack={setShowPatternPack}
                fusionReportId={fusionReportId}
                fusionReportData={fusionReportData}
                fusionReportSummary={fusionReportSummary}
                fusionReportError={fusionReportError}
                isFusionReportLoading={isFusionReportLoading}
                fusionConfidenceDisplay={fusionConfidenceDisplay}
                fusionConfidenceLabel={fusionConfidenceLabel}
                fusionRawDisplay={fusionRawDisplay}
                showFusionReport={showFusionReport}
                setShowFusionReport={setShowFusionReport}
                directionScorecardData={directionScorecardData}
                scorecardSummary={scorecardSummary}
                directionScorecardError={directionScorecardError}
                isDirectionScorecardLoading={isDirectionScorecardLoading}
                verificationReportId={verificationReportId}
                verificationReportData={verificationReportData}
                verificationSummary={verificationSummary}
                verificationReportError={verificationReportError}
                isVerificationReportLoading={isVerificationReportLoading}
                showVerificationReport={showVerificationReport}
                setShowVerificationReport={setShowVerificationReport}
                artifactEntries={artifactEntries}
                getAlertSeverityTone={getAlertSeverityTone}
                formatLabel={formatLabel}
                formatIndicatorValue={formatIndicatorValue}
                formatContributionValue={formatContributionValue}
                formatPrice={formatPrice}
                formatConfidence={formatConfidence}
                formatArtifactLabel={formatArtifactLabel}
                formatArtifactId={formatArtifactId}
                renderIndicatorHighlights={renderIndicatorHighlights}
                renderScorecardContributions={renderScorecardContributions}
            />
        </div >
    );
};

export const TechnicalAnalysisOutput = memo(TechnicalAnalysisOutputComponent);
