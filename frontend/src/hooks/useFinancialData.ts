import { useMemo } from 'react';
import { DimensionScore, StandardAgentOutput } from '@/types/agents';
import { FinancialReport, TraceableField } from '@/types/agents/fundamental';
import { isRecord } from '@/types/preview';

const getFieldValue = (field: TraceableField | null | undefined): number => {
    if (!field) return 0;
    if (typeof field.value === 'number') return field.value;
    if (typeof field.value === 'string') return parseFloat(field.value) || 0;
    return 0;
};

const isTraceableField = (value: unknown): value is TraceableField =>
    isRecord(value) && 'value' in value;

const getOptionalTraceableField = (
    source: unknown,
    key: string
): TraceableField | null => {
    if (!isRecord(source)) return null;
    const candidate = source[key];
    return isTraceableField(candidate) ? candidate : null;
};

const getScore = (
    val: number | null | undefined,
    min: number,
    max: number
): number => {
    if (val === null || val === undefined) return 50;
    const score = ((val - min) / (max - min)) * 100;
    return Math.min(Math.max(Math.round(score), 0), 100);
};

const getPreviewRecord = (
    output: StandardAgentOutput | null | undefined
): Record<string, unknown> | null => {
    const preview = output?.preview;
    return isRecord(preview) ? preview : null;
};

const getFinancialReports = (preview: Record<string, unknown> | null): FinancialReport[] => {
    const reports = preview?.financial_reports;
    return Array.isArray(reports) ? (reports as FinancialReport[]) : [];
};

const getRiskLevelScore = (
    preview: Record<string, unknown> | null
): number | null => {
    const signalState = preview?.signal_state;
    if (!isRecord(signalState)) return null;
    const riskLevel = signalState.risk_level;
    if (riskLevel === 'low') return 90;
    if (riskLevel === 'medium') return 60;
    return 20;
};

const getZScoreValuation = (
    preview: Record<string, unknown> | null
): number | null => {
    const signalState = preview?.signal_state;
    if (!isRecord(signalState)) return null;
    const zScore = signalState.z_score;
    if (typeof zScore !== 'number') return null;
    return Math.abs(zScore) > 2 ? 80 : 50;
};

const getResolvedTicker = (
    output: StandardAgentOutput | null | undefined
): string | null => {
    const preview = getPreviewRecord(output);
    if (!preview) return null;
    const ticker = preview.ticker;
    return typeof ticker === 'string' ? ticker : null;
};

export const useFinancialData = (
    agentId: string,
    allAgentOutputs: Record<string, StandardAgentOutput | null>
) => {
    return useMemo(() => {
        const intentOutput = allAgentOutputs.intent_extraction;
        const resolvedTicker = getResolvedTicker(intentOutput);

        const rawOutput = allAgentOutputs[agentId] ?? null;
        const preview = getPreviewRecord(rawOutput);
        const agentReports = getFinancialReports(preview);
        const latestReport = agentReports.length > 0 ? agentReports[0] : null;
        const previousBase = agentReports.length > 1 ? agentReports[1].base : null;
        const latestBase = latestReport?.base;

        const roe = latestBase
            ? getFieldValue(latestBase.net_income) /
              (getFieldValue(latestBase.total_equity) || 1)
            : 0;
        const debtToEquity = latestBase
            ? getFieldValue(latestBase.total_liabilities) /
              (getFieldValue(latestBase.total_equity) || 1)
            : 0;
        const currentRev = latestBase ? getFieldValue(latestBase.total_revenue) : 0;
        const prevRev = previousBase ? getFieldValue(previousBase.total_revenue) : 0;
        const revenueGrowth = currentRev && prevRev ? (currentRev - prevRev) / prevRev : 0.05;
        const peRatio = latestBase
            ? getFieldValue(getOptionalTraceableField(latestBase, 'pe_ratio'))
            : 20;

        const valuationScore =
            typeof preview?.valuation_score === 'number' ? preview.valuation_score : null;
        const riskScoreFromSignal = getRiskLevelScore(preview);
        const valuationFromSignal = getZScoreValuation(preview);
        const keyMetrics = isRecord(preview?.key_metrics)
            ? (preview.key_metrics as Record<string, string>)
            : {};

        const dimensionScores: DimensionScore[] = [
            {
                name: 'Fundamental',
                score: latestBase ? getScore(roe, 0, 0.3) : agentId === 'fundamental_analysis' ? 85 : 0,
                color: 'bg-emerald-500',
            },
            {
                name: 'Efficiency',
                score: latestBase ? getScore(roe > 0.15 ? 0.8 : 0.5, 0, 1) : agentId === 'fundamental_analysis' ? 65 : 0,
                color: 'bg-cyan-500',
            },
            {
                name: 'Risk',
                score: latestBase
                    ? 100 - getScore(debtToEquity, 0, 2)
                    : riskScoreFromSignal ?? (agentId === 'fundamental_analysis' ? 72 : 0),
                color: 'bg-emerald-500',
            },
            {
                name: 'Growth',
                score: latestBase ? getScore(revenueGrowth, -0.1, 0.3) : agentId === 'fundamental_analysis' ? 60 : 0,
                color: 'bg-cyan-500',
            },
            {
                name: 'Valuation',
                score: latestBase
                    ? 100 - getScore(peRatio, 10, 40)
                    : valuationScore ?? valuationFromSignal ?? (agentId === 'fundamental_analysis' ? 40 : 0),
                color: 'bg-rose-500',
            },
        ];

        const financialMetrics = [
            { label: 'ROE', value: latestBase ? `${(roe * 100).toFixed(1)}%` : keyMetrics.ROE || 'N/A' },
            { label: 'P/E Ratio', value: latestBase && peRatio ? peRatio.toFixed(1) : 'N/A' },
            { label: 'Debt/Equity', value: latestBase ? debtToEquity.toFixed(2) : 'N/A' },
            {
                label: 'Revenue',
                value: latestBase ? `$${(currentRev / 1e9).toFixed(1)}B` : keyMetrics.Revenue || 'N/A',
            },
        ];

        return {
            resolvedTicker: resolvedTicker || (typeof preview?.ticker === 'string' ? preview.ticker : null),
            latestReport,
            dimensionScores,
            financialMetrics,
            rawOutput,
        };
    }, [agentId, allAgentOutputs]);
};
