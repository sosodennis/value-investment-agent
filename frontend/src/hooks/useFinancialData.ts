import { useMemo } from 'react';
import { DimensionScore } from '@/types/agents';

// Helper to safely extract values
const getFieldValue = (field: any) => {
    if (!field) return 0;
    return typeof field.value === 'number' ? field.value : parseFloat(String(field.value)) || 0;
};

const getScore = (val: any, min: number, max: number) => {
    if (val === null || val === undefined) return 50;
    const score = ((val - min) / (max - min)) * 100;
    return Math.min(Math.max(Math.round(score), 0), 100);
};

export const useFinancialData = (agentId: string, allAgentOutputs: Record<string, any>) => {
    return useMemo(() => {
        // 1. Resolve Ticker (from Intent Extraction)
        const intentOutput = allAgentOutputs['intent_extraction'];
        const intentRaw = intentOutput?.['intent_extraction'] || intentOutput;
        const resolvedTicker = intentRaw?.artifact?.preview?.resolved_ticker ||
            intentRaw?.preview?.resolved_ticker;

        // 2. Resolve Agent Specific Output
        const rawOutput = allAgentOutputs[agentId];
        const outputData = rawOutput?.artifact?.preview || rawOutput?.preview;

        // 3. Extract Financial Reports & Metrics
        const agentReports = outputData?.financial_reports || [];
        const latestReport = agentReports.length > 0 ? agentReports[0] : null;
        const previousBase = agentReports.length > 1 ? agentReports[1].base : null;
        const latestBase = latestReport?.base;

        // 4. Compute Core Metrics
        const roe = latestBase ? (getFieldValue(latestBase.net_income) / (getFieldValue(latestBase.total_equity) || 1)) : 0;
        const debtToEquity = latestBase ? (getFieldValue(latestBase.total_liabilities) / (getFieldValue(latestBase.total_equity) || 1)) : 0;

        const currentRev = latestBase ? getFieldValue(latestBase.total_revenue) : 0;
        const prevRev = previousBase ? getFieldValue(previousBase.total_revenue) : 0;
        const revenueGrowth = (currentRev && prevRev) ? (currentRev - prevRev) / prevRev : 0.05;

        const peRatio = latestBase ? getFieldValue(latestBase.pe_ratio) : 20;

        // 5. Compute Dimension Scores
        const dimensionScores: DimensionScore[] = [
            {
                name: 'Fundamental',
                score: latestBase ? getScore(roe, 0, 0.3) :
                    (agentId === 'fundamental_analysis' ? 85 : 0),
                color: 'bg-emerald-500'
            },
            {
                name: 'Efficiency',
                score: latestBase ? getScore(roe > 0.15 ? 0.8 : 0.5, 0, 1) :
                    (agentId === 'fundamental_analysis' ? 65 : 0),
                color: 'bg-cyan-500'
            },
            {
                name: 'Risk',
                score: latestBase ? 100 - getScore(debtToEquity, 0, 2) :
                    (agentId === 'technical_analysis' && outputData ?
                        (outputData.signal_state?.risk_level === 'low' ? 90 :
                            outputData.signal_state?.risk_level === 'medium' ? 60 : 20) :
                        (agentId === 'auditor' ? 90 : (agentId === 'fundamental_analysis' ? 72 : 0))),
                color: 'bg-emerald-500'
            },
            {
                name: 'Growth',
                score: latestBase ? getScore(revenueGrowth, -0.1, 0.3) :
                    (agentId === 'fundamental_analysis' ? 60 : 0),
                color: 'bg-cyan-500'
            },
            {
                name: 'Valuation',
                score: latestBase ? 100 - getScore(peRatio, 10, 40) :
                    (outputData?.valuation_score !== undefined ? outputData.valuation_score :
                        (agentId === 'technical_analysis' && outputData ?
                            (Math.abs(outputData.signal_state?.z_score || 0) > 2 ? 80 : 50) :
                            (agentId === 'calculator' ? 88 : (agentId === 'fundamental_analysis' ? 40 : 0)))),
                color: 'bg-rose-500'
            },
        ];

        const financialMetrics = [
            { label: 'ROE', value: latestBase ? `${(roe * 100).toFixed(1)}%` : (outputData?.key_metrics?.ROE || 'N/A') },
            { label: 'P/E Ratio', value: latestBase && peRatio ? peRatio.toFixed(1) : 'N/A' },
            { label: 'Debt/Equity', value: latestBase ? debtToEquity.toFixed(2) : 'N/A' },
            { label: 'Revenue', value: latestBase ? `$${(currentRev / 1e9).toFixed(1)}B` : (outputData?.key_metrics?.Revenue || 'N/A') },
        ];

        return {
            resolvedTicker: resolvedTicker || outputData?.ticker,
            latestReport,
            dimensionScores,
            financialMetrics,
            rawOutput
        };
    }, [agentId, allAgentOutputs]);
};
