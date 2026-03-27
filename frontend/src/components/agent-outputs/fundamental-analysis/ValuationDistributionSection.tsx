import React, { useMemo, useState } from 'react';
import { ChartArea } from 'lucide-react';
import {
    Area,
    AreaChart,
    CartesianGrid,
    ReferenceLine,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts';
import type {
    ParsedAssumptionBreakdown,
    ParsedDistributionMetrics,
    ParsedDistributionScenarios,
} from '@/types/agents/fundamental-preview-parser';

type ScenarioCard = { key: 'bear' | 'base' | 'bull'; label: string; price: number };

type BandStatus =
    | 'inside_normal'
    | 'undervalued_medium'
    | 'overvalued_medium'
    | 'undervalued_high'
    | 'overvalued_high';

type DistributionLegendItem = {
    key: string;
    label: string;
    value: number;
    lineClassName: string;
    lineThicknessClassName?: string;
};

type DistributionLegendCandidate = Omit<DistributionLegendItem, 'value'> & {
    value: number | undefined;
};

type TooltipReferenceRow = { key: string; label: string; value: number | undefined };

type TooltipReferenceRowWithValue = { key: string; label: string; value: number };

type MonteCarloSummary = {
    executedIterations?: number;
    configuredIterations?: number;
    effectiveWindow?: number;
    converged?: boolean;
    medianDelta?: number;
    tolerance?: number;
    stoppedEarly?: boolean;
    psdRepaired?: boolean;
    batchEvaluatorUsed?: boolean;
    samplerType?: string;
    corrDiagnosticsAvailable?: boolean;
    corrPairsTotal?: number;
    corrPearsonMaxText?: string;
    corrSpearmanMaxText?: string;
    corrPearsonMaeText?: string;
    corrSpearmanMaeText?: string;
    asOf?: string;
};

export interface ValuationDistributionSectionProps {
    distributionSummary?: ParsedDistributionMetrics;
    distributionScenarios?: ParsedDistributionScenarios;
    assumptionBreakdown?: ParsedAssumptionBreakdown;
    intrinsicValue?: number;
    upsidePotential?: number;
    mcSummary: MonteCarloSummary;
}

const formatCurrency = (value: number): string => {
    return `$${value.toFixed(2)}`;
};

const coerceFiniteNumber = (value: unknown): number | undefined => {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string') {
        const parsed = Number(value);
        if (Number.isFinite(parsed)) return parsed;
    }
    return undefined;
};

export const ValuationDistributionSection: React.FC<ValuationDistributionSectionProps> = ({
    distributionSummary,
    distributionScenarios,
    assumptionBreakdown,
    intrinsicValue,
    upsidePotential,
    mcSummary,
}) => {
    const keyParamCurrentPrice = coerceFiniteNumber(
        assumptionBreakdown?.key_parameters?.current_price
    );
    const impliedCurrentPrice =
        typeof intrinsicValue === 'number' &&
        typeof upsidePotential === 'number' &&
        Number.isFinite(intrinsicValue) &&
        Number.isFinite(upsidePotential) &&
        upsidePotential > -0.99
            ? intrinsicValue / (1 + upsidePotential)
            : undefined;
    const currentPriceAnchor = keyParamCurrentPrice ?? impliedCurrentPrice;

    const scenarioCards = useMemo<ScenarioCard[]>(() => {
        if (distributionScenarios) {
            const rawCards: Array<{
                key: 'bear' | 'base' | 'bull';
                label: unknown;
                price: unknown;
            }> = [
                {
                    key: 'bear',
                    label: distributionScenarios.bear?.label,
                    price: distributionScenarios.bear?.price,
                },
                {
                    key: 'base',
                    label: distributionScenarios.base?.label,
                    price: distributionScenarios.base?.price,
                },
                {
                    key: 'bull',
                    label: distributionScenarios.bull?.label,
                    price: distributionScenarios.bull?.price,
                },
            ];
            return rawCards.filter((scenario): scenario is ScenarioCard => (
                typeof scenario.label === 'string' && typeof scenario.price === 'number'
            ));
        }
        if (!distributionSummary) return [];
        const bear = distributionSummary.percentile_5;
        const base = distributionSummary.median;
        const bull = distributionSummary.percentile_95;
        if (
            typeof bear !== 'number' ||
            typeof base !== 'number' ||
            typeof bull !== 'number'
        ) {
            return [];
        }
        return [
            { key: 'bear', label: 'P5 (Bear)', price: bear },
            { key: 'base', label: 'P50 (Base)', price: base },
            { key: 'bull', label: 'P95 (Bull)', price: bull },
        ];
    }, [distributionScenarios, distributionSummary]);

    const distributionChartData = useMemo(() => {
        if (!distributionSummary) return [];
        const mean = distributionSummary.mean;
        const median = distributionSummary.median;
        const p5 = distributionSummary.percentile_5;
        const p95 = distributionSummary.percentile_95;
        const std =
            distributionSummary.std ??
            (typeof p5 === 'number' && typeof p95 === 'number'
                ? (p95 - p5) / 3.29
                : undefined);

        if (typeof mean !== 'number' || typeof std !== 'number' || std <= 0) return [];

        const points: Array<{ x: number; density: number }> = [];
        const start = mean - (4 * std);
        const step = (8 * std) / 48;
        for (let i = 0; i <= 48; i += 1) {
            const x = start + (i * step);
            const z = (x - mean) / std;
            const density = Math.exp(-0.5 * z * z);
            points.push({ x, density });
        }
        if (typeof median === 'number') {
            points.push({ x: median, density: Math.exp(-0.5 * (((median - mean) / std) ** 2)) });
        }
        return points.sort((a, b) => a.x - b.x);
    }, [distributionSummary]);

    const [showDistributionCurve, setShowDistributionCurve] = useState(true);
    const canShowCurve = distributionChartData.length > 0;
    const shouldRenderCurve = canShowCurve && (scenarioCards.length === 0 || showDistributionCurve);

    const p5 = distributionSummary?.percentile_5;
    const p95 = distributionSummary?.percentile_95;
    const confidenceLeft = (() => {
        const p25 = distributionSummary?.percentile_25;
        if (typeof p25 === 'number') return p25;
        const median = distributionSummary?.median;
        const std = distributionSummary?.std;
        if (typeof median === 'number' && typeof std === 'number' && std > 0) {
            return median - (0.674 * std);
        }
        const p5 = distributionSummary?.percentile_5;
        const p95 = distributionSummary?.percentile_95;
        if (
            typeof median === 'number' &&
            typeof p5 === 'number' &&
            typeof p95 === 'number'
        ) {
            return median - (0.205 * (p95 - p5));
        }
        return undefined;
    })();
    const confidenceRight = (() => {
        const p75 = distributionSummary?.percentile_75;
        if (typeof p75 === 'number') return p75;
        const median = distributionSummary?.median;
        const std = distributionSummary?.std;
        if (typeof median === 'number' && typeof std === 'number' && std > 0) {
            return median + (0.674 * std);
        }
        const p5 = distributionSummary?.percentile_5;
        const p95 = distributionSummary?.percentile_95;
        if (
            typeof median === 'number' &&
            typeof p5 === 'number' &&
            typeof p95 === 'number'
        ) {
            return median + (0.205 * (p95 - p5));
        }
        return undefined;
    })();
    const bandStatus: BandStatus | undefined = (() => {
        if (typeof currentPriceAnchor !== 'number') return undefined;
        if (typeof p5 === 'number' && currentPriceAnchor < p5) return 'undervalued_high';
        if (typeof p95 === 'number' && currentPriceAnchor > p95) return 'overvalued_high';
        if (typeof confidenceLeft === 'number' && currentPriceAnchor < confidenceLeft) {
            return 'undervalued_medium';
        }
        if (typeof confidenceRight === 'number' && currentPriceAnchor > confidenceRight) {
            return 'overvalued_medium';
        }
        return 'inside_normal';
    })();
    const bandDeviationText = (() => {
        if (typeof currentPriceAnchor !== 'number') return undefined;
        if (bandStatus === 'undervalued_high' && typeof p5 === 'number' && p5 > 0) {
            const pct = ((p5 - currentPriceAnchor) / p5) * 100;
            return `${pct.toFixed(1)}% below P5`;
        }
        if (bandStatus === 'overvalued_high' && typeof p95 === 'number' && p95 > 0) {
            const pct = ((currentPriceAnchor - p95) / p95) * 100;
            return `${pct.toFixed(1)}% above P95`;
        }
        if (bandStatus === 'undervalued_medium' && typeof confidenceLeft === 'number' && confidenceLeft > 0) {
            const pct = ((confidenceLeft - currentPriceAnchor) / confidenceLeft) * 100;
            return `${pct.toFixed(1)}% below P25`;
        }
        if (bandStatus === 'overvalued_medium' && typeof confidenceRight === 'number' && confidenceRight > 0) {
            const pct = ((currentPriceAnchor - confidenceRight) / confidenceRight) * 100;
            return `${pct.toFixed(1)}% above P75`;
        }
        return 'within modeled band';
    })();
    const bandStatusBadge = (() => {
        if (bandStatus === 'undervalued_high') {
            return {
                label: 'Undervaluation: High',
                className: 'text-emerald-200 border-emerald-400/40 bg-emerald-500/10',
            };
        }
        if (bandStatus === 'overvalued_high') {
            return {
                label: 'Overvaluation: High',
                className: 'text-rose-200 border-rose-400/40 bg-rose-500/10',
            };
        }
        if (bandStatus === 'undervalued_medium') {
            return {
                label: 'Undervaluation: Medium',
                className: 'text-emerald-100 border-emerald-400/25 bg-emerald-500/5',
            };
        }
        if (bandStatus === 'overvalued_medium') {
            return {
                label: 'Overvaluation: Medium',
                className: 'text-rose-100 border-rose-400/25 bg-rose-500/5',
            };
        }
        if (bandStatus === 'inside_normal') {
            return {
                label: 'Within Modeled Range',
                className: 'text-cyan-100 border-cyan-400/25 bg-cyan-500/5',
            };
        }
        return undefined;
    })();
    const distributionLegendItems = [
        {
            key: 'p5',
            label: 'P5',
            value: p5,
            lineClassName: 'border-rose-400 border-dashed',
        },
        {
            key: 'p25',
            label: 'P25',
            value: confidenceLeft,
            lineClassName: 'border-emerald-400 border-dashed',
        },
        {
            key: 'p50',
            label: 'P50',
            value: distributionSummary?.median,
            lineClassName: 'border-emerald-500 border-dashed',
        },
        {
            key: 'p75',
            label: 'P75',
            value: confidenceRight,
            lineClassName: 'border-emerald-400 border-dashed',
        },
        {
            key: 'p95',
            label: 'P95',
            value: p95,
            lineClassName: 'border-cyan-400 border-dashed',
        },
        {
            key: 'current',
            label: 'Current',
            value: currentPriceAnchor,
            lineClassName: 'border-rose-300 border-dashed',
            lineThicknessClassName: 'border-t-2',
        },
    ].filter((item: DistributionLegendCandidate): item is DistributionLegendItem => (
        typeof item.value === 'number'
    ));
    const tooltipReferenceRows: TooltipReferenceRow[] = [
        { key: 'p5', label: 'P5', value: p5 },
        { key: 'p25', label: 'P25', value: confidenceLeft },
        { key: 'p50', label: 'P50', value: distributionSummary?.median },
        { key: 'p75', label: 'P75', value: confidenceRight },
        { key: 'p95', label: 'P95', value: p95 },
        { key: 'current', label: 'Current', value: currentPriceAnchor },
    ];
    const tooltipReferenceRowsWithValue = tooltipReferenceRows.filter(
        (row): row is TooltipReferenceRowWithValue => typeof row.value === 'number'
    );
    const tooltipReferenceTolerance = useMemo(() => {
        if (distributionChartData.length < 2) return 1;
        let totalDelta = 0;
        let count = 0;
        for (let index = 1; index < distributionChartData.length; index += 1) {
            const prev = distributionChartData[index - 1];
            const next = distributionChartData[index];
            const delta = Math.abs(next.x - prev.x);
            if (delta > 0) {
                totalDelta += delta;
                count += 1;
            }
        }
        const averageDelta = count > 0 ? totalDelta / count : 1;
        return Math.max(1, Math.min(6, averageDelta * 0.6));
    }, [distributionChartData]);
    const readPayloadX = (value: unknown): number | undefined => {
        if (typeof value !== 'object' || value === null) return undefined;
        return coerceFiniteNumber(Reflect.get(value, 'x'));
    };

    if (scenarioCards.length === 0 && distributionChartData.length === 0) {
        return null;
    }

    const {
        executedIterations: mcExecutedIterations,
        configuredIterations: mcConfiguredIterations,
        effectiveWindow: mcEffectiveWindow,
        converged: mcConverged,
        medianDelta: mcMedianDelta,
        tolerance: mcTolerance,
        stoppedEarly: mcStoppedEarly,
        psdRepaired: mcPsdRepaired,
        batchEvaluatorUsed: mcBatchEvaluatorUsed,
        samplerType: mcSamplerType,
        corrDiagnosticsAvailable: mcCorrDiagnosticsAvailable,
        corrPairsTotal: mcCorrPairsTotal,
        corrPearsonMaxText: mcCorrPearsonMaxText,
        corrSpearmanMaxText: mcCorrSpearmanMaxText,
        corrPearsonMaeText: mcCorrPearsonMaeText,
        corrSpearmanMaeText: mcCorrSpearmanMaeText,
        asOf: mcAsOf,
    } = mcSummary;

    const distributionAccessibilitySummary = (() => {
        if (!distributionSummary) return '';
        const summaryParts: string[] = ['Valuation distribution view.'];
        if (typeof distributionSummary.median === 'number') {
            summaryParts.push(`Median is ${formatCurrency(distributionSummary.median)}.`);
        }
        if (typeof currentPriceAnchor === 'number') {
            summaryParts.push(`Current price is ${formatCurrency(currentPriceAnchor)}.`);
        }
        if (bandStatusBadge?.label) {
            summaryParts.push(`${bandStatusBadge.label}.`);
        }
        if (bandDeviationText) {
            summaryParts.push(`Distance summary: ${bandDeviationText}.`);
        }
        if (typeof mcExecutedIterations === 'number') {
            summaryParts.push(`Monte Carlo executed iterations: ${Math.round(mcExecutedIterations)}.`);
        }
        if (typeof mcPsdRepaired === 'boolean') {
            summaryParts.push(`PSD repair: ${mcPsdRepaired ? 'applied' : 'not required'}.`);
        }
        return summaryParts.join(' ');
    })();

    return (
        <div className="bg-surface-container p-5 rounded-xl border border-outline-variant/10 space-y-5 flex flex-col">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <ChartArea size={16} className="text-primary-container" />
                    <span className="text-[10px] text-outline uppercase tracking-tighter">Valuation Distribution</span>
                </div>
                <div className="flex items-center gap-4">
                    {distributionSummary?.median !== undefined && (
                        <span className="text-sm font-black text-primary-fixed tabular-nums">
                            Median: {formatCurrency(distributionSummary.median)}
                        </span>
                    )}
                    {typeof currentPriceAnchor === 'number' && (
                        <span className="text-sm font-semibold text-rose-200 tabular-nums">
                            Current: {formatCurrency(currentPriceAnchor)}
                        </span>
                    )}
                </div>
            </div>
            {(bandStatusBadge || bandDeviationText) && (
                <div className="flex flex-wrap items-center gap-2">
                    {bandStatusBadge && (
                        <span
                            className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${bandStatusBadge.className}`}
                        >
                            {bandStatusBadge.label}
                        </span>
                    )}
                    {bandDeviationText && (
                        <span className="text-xs text-on-surface-variant">
                            {bandDeviationText}
                        </span>
                    )}
                </div>
            )}
            {distributionLegendItems.length > 0 && (
                <div className="flex flex-wrap items-center gap-2">
                    {distributionLegendItems.map((legendItem) => (
                        <div
                            key={legendItem.key}
                            className="inline-flex items-center gap-2 rounded-md border border-outline-variant/30 bg-surface-container-low px-2 py-1"
                        >
                            <span
                                className={`block w-4 border-t ${legendItem.lineThicknessClassName ?? ''} ${legendItem.lineClassName}`}
                                aria-hidden="true"
                            />
                            <span className="text-[11px] text-on-surface-variant">
                                {legendItem.label}: {formatCurrency(legendItem.value)}
                            </span>
                        </div>
                    ))}
                </div>
            )}
            {distributionAccessibilitySummary && (
                <p className="sr-only">{distributionAccessibilitySummary}</p>
            )}

            {scenarioCards.length > 0 && (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    {scenarioCards.map((scenario) => (
                        <div key={scenario.key} className="bg-surface-container p-5 rounded-xl border border-outline-variant/10">
                            <div className="text-[10px] text-outline mb-2 block uppercase tracking-tighter">{scenario.label}</div>
                            <div className="text-lg font-black text-on-surface tabular-nums tracking-tight">
                                {formatCurrency(scenario.price)}
                            </div>
                            {scenario.key === 'bear' && bandStatus === 'undervalued_high' && bandDeviationText && (
                                <div className="mt-1 text-[11px] text-emerald-300">
                                    Current is {bandDeviationText}
                                </div>
                            )}
                            {scenario.key === 'bull' && bandStatus === 'overvalued_high' && bandDeviationText && (
                                <div className="mt-1 text-[11px] text-rose-300">
                                    Current is {bandDeviationText}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {canShowCurve && scenarioCards.length > 0 && (
                <div className="flex items-center justify-between rounded-lg bg-surface-container px-3 py-2">
                    <div className="text-xs text-on-surface-variant">
                        The detailed distribution curve can be used to view tail risks (P5/P95).
                    </div>
                    <button
                        type="button"
                        className="text-xs font-semibold text-primary-container hover:text-primary-fixed transition-colors"
                        onClick={() => setShowDistributionCurve((current) => !current)}
                    >
                        {showDistributionCurve ? 'Hide Curve' : 'Show Curve'}
                    </button>
                </div>
            )}

            {shouldRenderCurve && (
                <div className="h-48 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={distributionChartData}>
                            <defs>
                                <linearGradient id="valuationDensity" x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="5%" stopColor="#22d3ee" stopOpacity={0.55} />
                                    <stop offset="95%" stopColor="#22d3ee" stopOpacity={0.05} />
                                </linearGradient>
                            </defs>
                            <CartesianGrid
                                stroke="rgba(148,163,184,0.12)"
                                strokeDasharray="3 3"
                                vertical={false}
                            />
                            <XAxis
                                type="number"
                                dataKey="x"
                                tick={{ fill: '#94a3b8', fontSize: 11 }}
                                tickFormatter={(value) => `$${Number(value).toFixed(0)}`}
                                tickCount={9}
                                minTickGap={24}
                                domain={[
                                    (dataMin: number) => {
                                        const anchors = [dataMin];
                                        if (typeof currentPriceAnchor === 'number') anchors.push(currentPriceAnchor);
                                        if (typeof confidenceLeft === 'number') anchors.push(confidenceLeft);
                                        return Math.min(...anchors);
                                    },
                                    (dataMax: number) => {
                                        const anchors = [dataMax];
                                        if (typeof currentPriceAnchor === 'number') anchors.push(currentPriceAnchor);
                                        if (typeof confidenceRight === 'number') anchors.push(confidenceRight);
                                        return Math.max(...anchors);
                                    },
                                ]}
                            />
                            <YAxis hide />
                            {typeof distributionSummary?.percentile_5 === 'number' && (
                                <ReferenceLine
                                    x={distributionSummary.percentile_5}
                                    stroke="#f43f5e"
                                    strokeDasharray="4 4"
                                />
                            )}
                            {typeof distributionSummary?.median === 'number' && (
                                <ReferenceLine
                                    x={distributionSummary.median}
                                    stroke="#10b981"
                                    strokeDasharray="4 4"
                                />
                            )}
                            {typeof confidenceLeft === 'number' && (
                                <ReferenceLine
                                    x={confidenceLeft}
                                    stroke="#34d399"
                                    strokeDasharray="3 3"
                                />
                            )}
                            {typeof confidenceRight === 'number' && (
                                <ReferenceLine
                                    x={confidenceRight}
                                    stroke="#34d399"
                                    strokeDasharray="3 3"
                                />
                            )}
                            {typeof distributionSummary?.percentile_95 === 'number' && (
                                <ReferenceLine
                                    x={distributionSummary.percentile_95}
                                    stroke="#22d3ee"
                                    strokeDasharray="4 4"
                                />
                            )}
                            {typeof currentPriceAnchor === 'number' && (
                                <ReferenceLine
                                    x={currentPriceAnchor}
                                    stroke="#fb7185"
                                    strokeWidth={2.5}
                                    strokeDasharray="6 4"
                                    ifOverflow="extendDomain"
                                />
                            )}
                            <Tooltip
                                contentStyle={{
                                    background: 'rgba(2, 6, 23, 0.95)',
                                    border: '1px solid rgba(34, 211, 238, 0.35)',
                                    borderRadius: 8,
                                    color: '#e2e8f0',
                                }}
                                cursor={{ stroke: 'rgba(34, 211, 238, 0.35)', strokeDasharray: '4 4' }}
                                content={({ active, payload }) => {
                                    const hoveredPrice = readPayloadX(payload?.[0]?.payload);
                                    if (!active || typeof hoveredPrice !== 'number') return null;
                                    const matchedReferences = tooltipReferenceRowsWithValue
                                        .map((row) => ({
                                            ...row,
                                            distance: Math.abs(row.value - hoveredPrice),
                                        }))
                                        .filter((row) => row.distance <= tooltipReferenceTolerance)
                                        .sort((left, right) => left.distance - right.distance);
                                    return (
                                        <div
                                            style={{
                                                background: 'rgba(2, 6, 23, 0.95)',
                                                border: '1px solid rgba(34, 211, 238, 0.35)',
                                                borderRadius: 8,
                                                color: '#e2e8f0',
                                                padding: '10px 12px',
                                                minWidth: 210,
                                            }}
                                        >
                                            <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>
                                                Hover Price: {formatCurrency(hoveredPrice)}
                                            </div>
                                            {matchedReferences.length > 0 && (
                                                <div style={{ display: 'grid', gap: 3 }}>
                                                    {matchedReferences.map((row) => (
                                                        <div
                                                            key={row.key}
                                                            style={{
                                                                display: 'flex',
                                                                justifyContent: 'space-between',
                                                                gap: 8,
                                                                fontSize: 11,
                                                            }}
                                                        >
                                                            <span style={{ color: '#94a3b8' }}>{row.label}</span>
                                                            <span style={{ color: '#e2e8f0' }}>
                                                                {formatCurrency(row.value)}
                                                            </span>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    );
                                }}
                            />
                            <Area
                                type="monotone"
                                dataKey="density"
                                stroke="#22d3ee"
                                fill="url(#valuationDensity)"
                                strokeWidth={2}
                                dot={false}
                            />
                        </AreaChart>
                    </ResponsiveContainer>
                </div>
            )}
            {(mcExecutedIterations !== undefined ||
                mcConfiguredIterations !== undefined ||
                mcEffectiveWindow !== undefined ||
                mcConverged !== undefined ||
                mcMedianDelta !== undefined ||
                mcPsdRepaired !== undefined ||
                mcBatchEvaluatorUsed !== undefined ||
                mcSamplerType !== undefined ||
                (mcCorrDiagnosticsAvailable &&
                    (mcCorrPairsTotal !== undefined ||
                        mcCorrPearsonMaxText !== undefined ||
                        mcCorrSpearmanMaxText !== undefined ||
                        mcCorrPearsonMaeText !== undefined ||
                        mcCorrSpearmanMaeText !== undefined)) ||
                mcAsOf) && (
                <div className="text-[11px] text-on-surface-variant">
                    {mcExecutedIterations !== undefined && (
                        <span>
                            MC runs: {Math.round(mcExecutedIterations)}
                            {mcConfiguredIterations !== undefined
                                ? ` / ${Math.round(mcConfiguredIterations)}`
                                : ''}
                        </span>
                    )}
                    {mcEffectiveWindow !== undefined && (
                        <span> · window: {Math.round(mcEffectiveWindow)}</span>
                    )}
                    {mcConverged !== undefined && (
                        <span> · converged: {mcConverged ? 'yes' : 'no'}</span>
                    )}
                    {mcMedianDelta !== undefined && (
                        <span>
                            {' '}
                            · median Δ: {(mcMedianDelta * 100).toFixed(2)}%
                            {mcTolerance !== undefined
                                ? ` (tol ${(mcTolerance * 100).toFixed(2)}%)`
                                : ''}
                        </span>
                    )}
                    {mcStoppedEarly !== undefined && (
                        <span>
                            {' '}
                            · early stop: {mcStoppedEarly ? 'yes' : 'no'}
                        </span>
                    )}
                    {mcPsdRepaired !== undefined && (
                        <span> · psd repaired: {mcPsdRepaired ? 'yes' : 'no'}</span>
                    )}
                    {mcBatchEvaluatorUsed !== undefined && (
                        <span>
                            {' '}
                            · batch eval: {mcBatchEvaluatorUsed ? 'yes' : 'no'}
                        </span>
                    )}
                    {mcSamplerType !== undefined && (
                        <span> · sampler: {mcSamplerType}</span>
                    )}
                    {mcCorrDiagnosticsAvailable && (
                        <>
                            {mcCorrPairsTotal !== undefined && (
                                <span> · corr pairs: {Math.round(mcCorrPairsTotal)}</span>
                            )}
                            {(mcCorrPearsonMaxText || mcCorrSpearmanMaxText) && (
                                <span>
                                    {' '}
                                    · corr max err (P/S): {mcCorrPearsonMaxText ?? 'n/a'} /{' '}
                                    {mcCorrSpearmanMaxText ?? 'n/a'}
                                </span>
                            )}
                            {(mcCorrPearsonMaeText || mcCorrSpearmanMaeText) && (
                                <span>
                                    {' '}
                                    · corr MAE (P/S): {mcCorrPearsonMaeText ?? 'n/a'} /{' '}
                                    {mcCorrSpearmanMaeText ?? 'n/a'}
                                </span>
                            )}
                        </>
                    )}
                    {mcAsOf && <span> · as-of: {mcAsOf}</span>}
                </div>
            )}
        </div>
    );
};
