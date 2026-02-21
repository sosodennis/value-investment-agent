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
                                {distributionSummary?.median !== undefined && (
                                    <span className="text-sm font-black text-cyan-200">
                                        Median: {formatCurrency(distributionSummary.median)}
                                    </span>
                                )}
                            </div>

                            {scenarioCards.length > 0 && (
                                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                    {scenarioCards.map((scenario) => (
                                        <div key={scenario.key} className="rounded-lg border border-white/10 bg-slate-900/40 p-3">
                                            <div className="text-label mb-1">{scenario.label}</div>
                                            <div className="text-lg font-black text-white">
                                                {formatCurrency(scenario.price)}
                                            </div>
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
                                            <CartesianGrid stroke="rgba(148,163,184,0.15)" strokeDasharray="3 3" />
                                            <XAxis
                                                dataKey="x"
                                                tick={{ fill: '#94a3b8', fontSize: 11 }}
                                                tickFormatter={(value) => `$${Number(value).toFixed(0)}`}
                                            />
                                            <YAxis hide />
                                            {typeof distributionSummary?.percentile_5 === 'number' && (
                                                <ReferenceLine
                                                    x={distributionSummary.percentile_5}
                                                    stroke="#f43f5e"
                                                    strokeDasharray="4 4"
                                                    label={{ value: 'P5', fill: '#f43f5e', position: 'insideTopRight', fontSize: 10 }}
                                                />
                                            )}
                                            {typeof distributionSummary?.median === 'number' && (
                                                <ReferenceLine
                                                    x={distributionSummary.median}
                                                    stroke="#10b981"
                                                    strokeDasharray="4 4"
                                                    label={{ value: 'P50', fill: '#10b981', position: 'insideTopRight', fontSize: 10 }}
                                                />
                                            )}
                                            {typeof distributionSummary?.percentile_95 === 'number' && (
                                                <ReferenceLine
                                                    x={distributionSummary.percentile_95}
                                                    stroke="#22d3ee"
                                                    strokeDasharray="4 4"
                                                    label={{ value: 'P95', fill: '#22d3ee', position: 'insideTopRight', fontSize: 10 }}
                                                />
                                            )}
                                            <Tooltip
                                                contentStyle={{
                                                    background: 'rgba(2, 6, 23, 0.95)',
                                                    border: '1px solid rgba(34, 211, 238, 0.35)',
                                                    borderRadius: 8,
                                                    color: '#e2e8f0',
                                                }}
                                                formatter={(_value, _name, item) => [formatCurrency(Number(item.payload?.x ?? 0)), 'Price']}
                                                labelFormatter={() => 'Modeled Density'}
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
