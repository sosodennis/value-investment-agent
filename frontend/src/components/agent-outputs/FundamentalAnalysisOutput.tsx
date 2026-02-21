import React, { memo, useMemo, useState } from 'react';
import { LayoutPanelTop, BarChart3, ChartArea } from 'lucide-react';
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
import { FinancialTable } from '../FinancialTable';
import { AgentStatus, ArtifactReference } from '@/types/agents';
import { parseFundamentalArtifact } from '@/types/agents/artifact-parsers';
import { ParsedFinancialPreview } from '@/types/agents/fundamental-preview-parser';
import { useArtifact } from '../../hooks/useArtifact';
import { AgentLoadingState } from './AgentLoadingState';

export interface FundamentalAnalysisOutputProps {
    reference: ArtifactReference | null;
    previewData: ParsedFinancialPreview | null;
    resolvedTicker: string | null | undefined;
    status: AgentStatus;
}

const FundamentalAnalysisOutputComponent: React.FC<FundamentalAnalysisOutputProps> = ({
    reference,
    previewData,
    resolvedTicker,
    status
}) => {
    const { data: artifactData, isLoading: isArtifactLoading } = useArtifact(
        reference?.artifact_id,
        parseFundamentalArtifact,
        'fundamental_output.artifact',
        'financial_reports'
    );

    const hasPreview = !!previewData;
    const reports = artifactData?.financial_reports ?? previewData?.financial_reports ?? [];
    const valuationScore = previewData?.valuation_score;
    const previewKeyMetrics = previewData?.key_metrics ?? {};
    const distributionSummary = previewData?.distribution_summary?.summary;
    const distributionScenarios = previewData?.distribution_scenarios;
    const assumptionBreakdown = previewData?.assumption_breakdown;
    const dataFreshness = previewData?.data_freshness;
    const equityValue = previewData?.equity_value;
    const intrinsicValue = previewData?.intrinsic_value;
    const upsidePotential = previewData?.upside_potential;
    const coerceFiniteNumber = (value: unknown): number | undefined => {
        if (typeof value === 'number' && Number.isFinite(value)) return value;
        if (typeof value === 'string') {
            const parsed = Number(value);
            if (Number.isFinite(parsed)) return parsed;
        }
        return undefined;
    };
    type ScenarioCard = { key: 'bear' | 'base' | 'bull'; label: string; price: number };

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
    const [showDistributionCurve, setShowDistributionCurve] = useState(false);
    const canShowCurve = distributionChartData.length > 0;
    const shouldRenderCurve = canShowCurve && (scenarioCards.length === 0 || showDistributionCurve);
    const assumptionHighlights = useMemo(
        () => assumptionBreakdown?.assumptions?.slice(0, 3) ?? [],
        [assumptionBreakdown]
    );
    const monteCarloMeta = assumptionBreakdown?.monte_carlo;
    const mcExecutedIterations =
        typeof monteCarloMeta?.executed_iterations === 'number'
            ? monteCarloMeta.executed_iterations
            : undefined;
    const mcEffectiveWindow =
        typeof monteCarloMeta?.effective_window === 'number'
            ? monteCarloMeta.effective_window
            : undefined;
    const mcStoppedEarly =
        typeof monteCarloMeta?.stopped_early === 'boolean'
            ? monteCarloMeta.stopped_early
            : undefined;
    const mcConfiguredIterations =
        typeof monteCarloMeta?.configured_iterations === 'number'
            ? monteCarloMeta.configured_iterations
            : undefined;
    const mcAsOf = dataFreshness?.market_data?.as_of;
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
    type BandStatus =
        | 'inside_normal'
        | 'undervalued_medium'
        | 'overvalued_medium'
        | 'undervalued_high'
        | 'overvalued_high';
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
    type TooltipReferenceRow = { key: string; label: string; value: number | undefined };
    type TooltipReferenceRowWithValue = { key: string; label: string; value: number };
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
    type ValuationCard = {
        label: string;
        value: string;
        tone?: 'bull' | 'bear';
        unavailable?: boolean;
    };
    const valuationCards: ValuationCard[] = [
        {
            label: 'Intrinsic Value',
            value:
                typeof intrinsicValue === 'number'
                    ? formatCurrencyCompact(intrinsicValue)
                    : 'N/A',
            unavailable: typeof intrinsicValue !== 'number',
        },
        {
            label: 'Equity Value',
            value:
                typeof equityValue === 'number'
                    ? formatCurrencyCompact(equityValue)
                    : 'N/A',
            unavailable: typeof equityValue !== 'number',
        },
        {
            label: 'Upside Potential',
            value:
                typeof upsidePotential === 'number'
                    ? formatPercent(upsidePotential)
                    : 'N/A',
            tone:
                typeof upsidePotential === 'number'
                    ? upsidePotential >= 0
                        ? 'bull'
                        : 'bear'
                    : undefined,
            unavailable: typeof upsidePotential !== 'number',
        },
    ];
    const hasValuationValue = valuationCards.some((card) => !card.unavailable);

    const formatCurrency = (value: number): string => {
        return `$${value.toFixed(2)}`;
    };

    function formatCurrencyCompact(value: number): string {
        const abs = Math.abs(value);
        if (abs >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(2)}B`;
        if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
        if (abs >= 1_000) return `$${(value / 1_000).toFixed(2)}K`;
        return `$${value.toFixed(2)}`;
    }

    function formatPercent(value: number): string {
        const pct = value * 100;
        return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
    }
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
        return summaryParts.join(' ');
    })();

    if (status !== 'done' && reports.length === 0 && !hasPreview) {
        return (
            <AgentLoadingState
                type="full"
                icon={BarChart3}
                title="Processing Financials..."
                description="Extracting and analyzing financial data from 10-K/10-Q reports."
                status={status}
            />
        );
    }

    const isReferenceLoading = reference && isArtifactLoading && !artifactData;

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-3">
                    <LayoutPanelTop size={18} className="text-indigo-400" />
                    <h3 className="text-sm font-bold text-white uppercase tracking-widest">Financial Data Matrix</h3>
                </div>
                {isReferenceLoading && (
                    <AgentLoadingState
                        type="header"
                        title="Loading Reports..."
                        colorClass="text-indigo-400"
                    />
                )}
            </div>

            {/* Preview Section - Valuation & Metrics */}
            {hasPreview && (
                <div className="space-y-4 animate-slide-up">
                    <div className="tech-card p-4 flex items-center justify-between bg-gradient-to-r from-slate-900/40 to-slate-900/10">
                        <span className="text-label">Analyst Valuation Score</span>
                        {valuationScore !== undefined && (
                            <div className="flex items-center gap-3">
                                <div className="h-1 w-24 bg-slate-800 rounded-full overflow-hidden">
                                    <div
                                        className={`h-full transition-all duration-1000 ${valuationScore > 70 ? 'bg-emerald-500' : valuationScore < 40 ? 'bg-rose-500' : 'bg-amber-500'}`}
                                        style={{ width: `${valuationScore}%` }}
                                    />
                                </div>
                                <span className={`text-base font-black ${valuationScore > 70 ? 'text-emerald-400' : valuationScore < 40 ? 'text-rose-400' : 'text-amber-400'}`}>
                                    {Math.round(valuationScore)}/100
                                </span>
                            </div>
                        )}
                    </div>

                    {Object.keys(previewKeyMetrics).length > 0 && (
                        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                            {Object.entries(previewKeyMetrics).map(([label, value]) => (
                                <div key={label} className="tech-card p-4 group hover:bg-slate-900/40">
                                    <div className="text-label mb-1 text-slate-600 group-hover:text-slate-400 transition-colors">{label}</div>
                                    <div className="text-sm font-black text-white">
                                        {typeof value === 'string' ? value : String(value)}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}

                    <div className="space-y-2">
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                            {valuationCards.map((card) => (
                                <div
                                    key={card.label}
                                    className="tech-card p-4 border-white/10 bg-slate-900/40"
                                >
                                    <div className="text-label mb-1">{card.label}</div>
                                    <div
                                        className={`text-xl font-black ${
                                            card.unavailable
                                                ? 'text-slate-400'
                                                : card.tone === 'bull'
                                                    ? 'text-emerald-300'
                                                    : card.tone === 'bear'
                                                        ? 'text-rose-300'
                                                        : 'text-white'
                                        }`}
                                    >
                                        {card.value}
                                    </div>
                                </div>
                            ))}
                        </div>
                        {!hasValuationValue && (
                            <div className="text-xs text-amber-300">
                                Valuation metrics unavailable in this run. Check Logs for calculator details.
                            </div>
                        )}
                    </div>

                    {(assumptionBreakdown || dataFreshness) && (
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                            {assumptionBreakdown && (
                                <div className="tech-card p-4 space-y-3 border-amber-500/20 bg-gradient-to-br from-amber-950/20 via-slate-900/40 to-slate-950/20">
                                    <div className="flex items-center justify-between">
                                        <span className="text-label">Assumption Breakdown</span>
                                        <span className="text-xs font-semibold text-amber-300">
                                            {assumptionBreakdown.total_assumptions ?? 0} assumptions
                                        </span>
                                    </div>
                                    {typeof assumptionBreakdown.monte_carlo?.enabled === 'boolean' && (
                                        <div className="text-xs text-slate-300">
                                            Monte Carlo: {assumptionBreakdown.monte_carlo.enabled ? 'Enabled' : 'Disabled'}
                                        </div>
                                    )}
                                    {(mcExecutedIterations !== undefined ||
                                        mcEffectiveWindow !== undefined ||
                                        mcStoppedEarly !== undefined) && (
                                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                                            {mcExecutedIterations !== undefined && (
                                                <div className="text-[11px] text-slate-200 bg-slate-900/40 rounded px-2 py-1">
                                                    Executed: {Math.round(mcExecutedIterations)}
                                                </div>
                                            )}
                                            {mcEffectiveWindow !== undefined && (
                                                <div className="text-[11px] text-slate-200 bg-slate-900/40 rounded px-2 py-1">
                                                    Window: {Math.round(mcEffectiveWindow)}
                                                </div>
                                            )}
                                            {mcStoppedEarly !== undefined && (
                                                <div className="text-[11px] text-slate-200 bg-slate-900/40 rounded px-2 py-1">
                                                    Early Stop: {mcStoppedEarly ? 'Yes' : 'No'}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                    {assumptionHighlights.length > 0 && (
                                        <div className="space-y-2">
                                            {assumptionHighlights.map((item, index) => (
                                                <div key={`${item.statement}-${index}`} className="text-xs text-slate-200 bg-slate-900/40 rounded px-2 py-1">
                                                    {item.statement}
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}

                            {dataFreshness && (
                                <div className="tech-card p-4 space-y-3 border-emerald-500/20 bg-gradient-to-br from-emerald-950/20 via-slate-900/40 to-slate-950/20">
                                    <span className="text-label">Data Freshness</span>
                                    <div className="space-y-1 text-xs text-slate-200">
                                        {dataFreshness.financial_statement?.period_end_date && (
                                            <div>
                                                Financial Period End: {dataFreshness.financial_statement.period_end_date}
                                            </div>
                                        )}
                                        {typeof dataFreshness.financial_statement?.fiscal_year === 'number' && (
                                            <div>
                                                Fiscal Year: {dataFreshness.financial_statement.fiscal_year}
                                            </div>
                                        )}
                                        {dataFreshness.market_data?.provider && (
                                            <div>
                                                Market Provider: {dataFreshness.market_data.provider}
                                            </div>
                                        )}
                                        {dataFreshness.market_data?.as_of && (
                                            <div>
                                                Market As-Of: {dataFreshness.market_data.as_of}
                                            </div>
                                        )}
                                        {dataFreshness.shares_outstanding_source && (
                                            <div>
                                                Shares Source: {dataFreshness.shares_outstanding_source}
                                            </div>
                                        )}
                                        {dataFreshness.time_alignment?.status && (
                                            <div>
                                                Time Alignment Status:{' '}
                                                <span
                                                    className={
                                                        dataFreshness.time_alignment.status === 'high_risk'
                                                            ? 'text-rose-300 font-semibold'
                                                            : 'text-emerald-300 font-semibold'
                                                    }
                                                >
                                                    {dataFreshness.time_alignment.status}
                                                </span>
                                            </div>
                                        )}
                                        {typeof dataFreshness.time_alignment?.lag_days === 'number' && (
                                            <div>
                                                Time Alignment Lag: {Math.round(dataFreshness.time_alignment.lag_days)} days
                                                {typeof dataFreshness.time_alignment?.threshold_days === 'number'
                                                    ? ` (threshold ${Math.round(dataFreshness.time_alignment.threshold_days)} days)`
                                                    : ''}
                                            </div>
                                        )}
                                        {dataFreshness.time_alignment?.policy && (
                                            <div>
                                                Time Alignment Policy: {dataFreshness.time_alignment.policy}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {(scenarioCards.length > 0 || distributionChartData.length > 0) && (
                        <div className="tech-card p-5 space-y-4 bg-gradient-to-br from-cyan-950/20 via-slate-900/40 to-slate-950/20 border-cyan-500/20">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <ChartArea size={16} className="text-cyan-300" />
                                    <span className="text-label">Valuation Distribution</span>
                                </div>
                                <div className="flex items-center gap-4">
                                    {distributionSummary?.median !== undefined && (
                                        <span className="text-sm font-black text-cyan-200">
                                            Median: {formatCurrency(distributionSummary.median)}
                                        </span>
                                    )}
                                    {typeof currentPriceAnchor === 'number' && (
                                        <span className="text-sm font-semibold text-rose-200">
                                            Current: {formatCurrency(currentPriceAnchor)}
                                        </span>
                                    )}
                                </div>
                            </div>
                            {(bandStatusBadge || bandDeviationText) && (
                                <div className="flex flex-wrap items-center gap-2">
                                    {bandStatusBadge && (
                                        <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${bandStatusBadge.className}`}>
                                            {bandStatusBadge.label}
                                        </span>
                                    )}
                                    {bandDeviationText && (
                                        <span className="text-xs text-slate-300">
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
                                            className="inline-flex items-center gap-2 rounded-md border border-white/10 bg-slate-900/40 px-2 py-1"
                                        >
                                            <span
                                                className={`block w-4 border-t ${legendItem.lineThicknessClassName ?? ''} ${legendItem.lineClassName}`}
                                                aria-hidden="true"
                                            />
                                            <span className="text-[11px] text-slate-300">
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
                                        <div key={scenario.key} className="rounded-lg border border-white/10 bg-slate-900/40 p-3">
                                            <div className="text-label mb-1">{scenario.label}</div>
                                            <div className="text-lg font-black text-white">
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
                                <div className="flex items-center justify-between rounded-lg border border-cyan-400/20 bg-slate-900/40 px-3 py-2">
                                    <div className="text-xs text-slate-300">
                                        詳細分佈曲線可用於查看尾部風險（P5/P95）。
                                    </div>
                                    <button
                                        type="button"
                                        className="text-xs font-semibold text-cyan-300 hover:text-cyan-200 transition-colors"
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
                                mcAsOf) && (
                                <div className="text-[11px] text-slate-300">
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
                                    {mcStoppedEarly !== undefined && (
                                        <span>
                                            {' '}
                                            · early stop: {mcStoppedEarly ? 'yes' : 'no'}
                                        </span>
                                    )}
                                    {mcAsOf && <span> · as-of: {mcAsOf}</span>}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            {reports.length > 0 ? (
                <FinancialTable
                    reports={reports}
                    ticker={resolvedTicker || 'N/A'}
                />
            ) : (
                <AgentLoadingState
                    type="block"
                    title={isReferenceLoading ? "Loading financial reports..." : "No financial reports generated."}
                    colorClass="text-indigo-400"
                />
            )}
        </div>
    );
};

// Export with explicit props generic to stabilize memoized component type inference.
export const FundamentalAnalysisOutput = memo<FundamentalAnalysisOutputProps>(
    FundamentalAnalysisOutputComponent
);
