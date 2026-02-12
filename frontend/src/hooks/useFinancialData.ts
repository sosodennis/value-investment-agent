import { useMemo } from 'react';
import { DimensionScore, StandardAgentOutput } from '@/types/agents';
import { TraceableField } from '@/types/agents/fundamental';
import { ParsedSignalState } from '@/types/agents/fundamental-preview-parser';
import { parseFundamentalPreviewFromOutput } from '@/types/agents/output-adapter';
import { isRecord } from '@/types/preview';

const getFieldValue = (field: TraceableField | null | undefined): number => {
    if (!field) return 0;
    if (typeof field.value === 'number') return field.value;
    if (typeof field.value === 'string') return parseFloat(field.value) || 0;
    return 0;
};

const isTraceableField = (value: unknown): value is TraceableField =>
    typeof value === 'object' && value !== null && 'value' in value;

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

const getRiskLevelScore = (signalState: ParsedSignalState | undefined): number | null => {
    if (!signalState) return null;
    const riskLevel = signalState.risk_level;
    if (riskLevel === 'low') return 90;
    if (riskLevel === 'medium') return 60;
    return 20;
};

const getZScoreValuation = (signalState: ParsedSignalState | undefined): number | null => {
    if (!signalState) return null;
    return Math.abs(signalState.z_score) > 2 ? 80 : 50;
};

const getResolvedTicker = (
    output: StandardAgentOutput | null | undefined
): string | null => {
    const parsed = parseFundamentalPreviewFromOutput(
        output ?? null,
        'intent_extraction'
    );
    return parsed?.ticker ?? null;
};

export const useFinancialData = (
    agentId: string,
    allAgentOutputs: Record<string, StandardAgentOutput | null>
) => {
    return useMemo(() => {
        const intentOutput = allAgentOutputs.intent_extraction;
        const resolvedTicker = getResolvedTicker(intentOutput);

        const rawOutput = allAgentOutputs[agentId] ?? null;
        const parsedPreview = parseFundamentalPreviewFromOutput(
            rawOutput,
            `${agentId}`
        );
        const agentReports = parsedPreview?.financial_reports ?? [];
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

        const valuationScore = parsedPreview?.valuation_score ?? null;
        const riskScoreFromSignal = getRiskLevelScore(parsedPreview?.signal_state);
        const valuationFromSignal = getZScoreValuation(parsedPreview?.signal_state);
        const keyMetrics = parsedPreview?.key_metrics ?? {};

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
            resolvedTicker: resolvedTicker || parsedPreview?.ticker || null,
            latestReport,
            dimensionScores,
            financialMetrics,
            rawOutput,
        };
    }, [agentId, allAgentOutputs]);
};
