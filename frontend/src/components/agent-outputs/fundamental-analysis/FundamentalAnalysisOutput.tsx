import React, { memo, useMemo, useState } from 'react';
import { BarChart3, ExternalLink, LayoutPanelTop } from 'lucide-react';
import { FinancialTable } from './FinancialTable';
import { AgentStatus, ArtifactReference } from '@/types/agents';
import { parseFundamentalArtifact } from '@/types/agents/artifact-parsers';
import { ForwardSignal } from '@/types/agents/fundamental';
import { ParsedFinancialPreview } from '@/types/agents/fundamental-preview-parser';
import { useArtifact } from '../../../hooks/useArtifact';
import { AgentLoadingState } from '../shared/AgentLoadingState';
import { ValuationDistributionSection } from './ValuationDistributionSection';

const MODEL_LABEL_BY_TYPE: Record<string, string> = {
    dcf_standard: 'DCF (Standard)',
    dcf_growth: 'DCF (Growth)',
    saas: 'SaaS DCF',
    bank: 'Bank (DDM)',
    reit_ffo: 'REIT (FFO)',
    ev_revenue: 'EV/Revenue',
    ev_ebitda: 'EV/EBITDA',
    residual_income: 'Residual Income',
    eva: 'EVA',
    ddm: 'DDM',
    ffo: 'FFO',
    dcf: 'DCF',
};

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
    const [expandedEvidenceRows, setExpandedEvidenceRows] = useState<Record<string, boolean>>(
        {}
    );
    const reports = artifactData?.financial_reports ?? previewData?.financial_reports ?? [];
    const forwardSignals: ForwardSignal[] = artifactData?.forward_signals ?? [];
    const modelTypeRaw = artifactData?.model_type;
    const modelTypeDisplay = useMemo(() => {
        if (!modelTypeRaw || typeof modelTypeRaw !== 'string') return null;
        const normalized = modelTypeRaw.trim().toLowerCase();
        if (!normalized) return null;
        const label = MODEL_LABEL_BY_TYPE[normalized] ?? normalized;
        return { label, code: normalized };
    }, [modelTypeRaw]);
    const valuationScore = previewData?.valuation_score;
    const previewKeyMetrics = previewData?.key_metrics ?? {};
    const distributionSummary = previewData?.distribution_summary?.summary;
    const distributionDiagnostics = previewData?.distribution_summary?.diagnostics;
    const distributionScenarios = previewData?.distribution_scenarios;
    const valuationDiagnostics = previewData?.valuation_diagnostics;
    const sensitivitySummary = valuationDiagnostics?.sensitivity_summary;
    const growthConsensusPolicy = valuationDiagnostics?.growth_consensus_policy;
    const growthConsensusHorizon = valuationDiagnostics?.growth_consensus_horizon;
    const terminalAnchorPolicy = valuationDiagnostics?.terminal_anchor_policy;
    const terminalAnchorStaleFallback =
        valuationDiagnostics?.terminal_anchor_stale_fallback;
    const growthConsensusPolicyLabel = useMemo(() => {
        if (!growthConsensusPolicy) return null;
        if (growthConsensusPolicy === 'ignored') return 'Ignored';
        if (growthConsensusPolicy === 'included') return 'Included';
        if (growthConsensusPolicy === 'compatibility_assumed') {
            return 'Compatibility Assumed';
        }
        return growthConsensusPolicy;
    }, [growthConsensusPolicy]);
    const terminalAnchorPolicyLabel = useMemo(() => {
        if (!terminalAnchorPolicy) return null;
        if (terminalAnchorPolicy === 'policy_default_market_stale') {
            return 'Policy Default (Market Stale)';
        }
        return terminalAnchorPolicy;
    }, [terminalAnchorPolicy]);
    const assumptionBreakdown = previewData?.assumption_breakdown;
    const baseAssumptionGuardrailSummary = assumptionBreakdown?.base_assumption_guardrail;
    const dataFreshness = previewData?.data_freshness;
    const assumptionRiskLevel =
        previewData?.assumption_risk_level ?? assumptionBreakdown?.assumption_risk_level;
    const dataQualityFlags = (
        previewData?.data_quality_flags ??
        assumptionBreakdown?.data_quality_flags ??
        []
    ).filter((flag): flag is string => typeof flag === 'string' && flag.length > 0);
    const dataQualityFlagsPreview = dataQualityFlags.slice(0, 6);
    const dataQualityFlagsOverflow =
        dataQualityFlags.length > dataQualityFlagsPreview.length
            ? dataQualityFlags.length - dataQualityFlagsPreview.length
            : 0;
    const timeAlignmentStatus =
        previewData?.time_alignment_status ??
        assumptionBreakdown?.time_alignment_status ??
        dataFreshness?.time_alignment?.status;
    const forwardSignalSummary =
        previewData?.forward_signal_summary ??
        assumptionBreakdown?.forward_signal_summary;
    const forwardSignalRiskLevel =
        previewData?.forward_signal_risk_level ??
        assumptionBreakdown?.forward_signal_risk_level ??
        forwardSignalSummary?.risk_level;
    const forwardSignalEvidenceCount =
        previewData?.forward_signal_evidence_count ??
        assumptionBreakdown?.forward_signal_evidence_count ??
        forwardSignalSummary?.evidence_count;
    const forwardSignalSourceTypes = (forwardSignalSummary?.source_types ?? []).filter(
        (item): item is string => typeof item === 'string' && item.length > 0
    );
    const forwardSignalSourcePreview = forwardSignalSourceTypes.slice(0, 2);
    const forwardSignalSourceOverflow =
        forwardSignalSourceTypes.length > forwardSignalSourcePreview.length
            ? forwardSignalSourceTypes.length - forwardSignalSourcePreview.length
            : 0;
    const forwardSignalMappingVersion =
        typeof valuationDiagnostics?.forward_signal_mapping_version === 'string' &&
        valuationDiagnostics.forward_signal_mapping_version.length > 0
            ? valuationDiagnostics.forward_signal_mapping_version
            : typeof forwardSignalSummary?.mapping_version === 'string' &&
                forwardSignalSummary.mapping_version.length > 0
                ? forwardSignalSummary.mapping_version
            : undefined;
    const forwardSignalCalibrationApplied =
        typeof valuationDiagnostics?.forward_signal_calibration_applied === 'boolean'
            ? valuationDiagnostics.forward_signal_calibration_applied
            : typeof forwardSignalSummary?.calibration_applied === 'boolean'
            ? forwardSignalSummary.calibration_applied
            : undefined;
    const baseGrowthGuardrailApplied =
        typeof valuationDiagnostics?.base_growth_guardrail_applied === 'boolean'
            ? valuationDiagnostics.base_growth_guardrail_applied
            : typeof baseAssumptionGuardrailSummary?.growth?.applied === 'boolean'
            ? baseAssumptionGuardrailSummary.growth.applied
            : undefined;
    const baseGrowthGuardrailVersion =
        typeof valuationDiagnostics?.base_growth_guardrail_version === 'string' &&
        valuationDiagnostics.base_growth_guardrail_version.length > 0
            ? valuationDiagnostics.base_growth_guardrail_version
            : typeof baseAssumptionGuardrailSummary?.growth?.version === 'string' &&
                baseAssumptionGuardrailSummary.growth.version.length > 0
            ? baseAssumptionGuardrailSummary.growth.version
            : typeof baseAssumptionGuardrailSummary?.version === 'string' &&
                baseAssumptionGuardrailSummary.version.length > 0
            ? baseAssumptionGuardrailSummary.version
            : undefined;
    const baseGrowthRawYear1 =
        typeof valuationDiagnostics?.base_growth_raw_year1 === 'number'
            ? valuationDiagnostics.base_growth_raw_year1
            : typeof baseAssumptionGuardrailSummary?.growth?.raw_year1 === 'number'
            ? baseAssumptionGuardrailSummary.growth.raw_year1
            : undefined;
    const baseGrowthRawYearN =
        typeof valuationDiagnostics?.base_growth_raw_yearN === 'number'
            ? valuationDiagnostics.base_growth_raw_yearN
            : typeof baseAssumptionGuardrailSummary?.growth?.raw_yearN === 'number'
            ? baseAssumptionGuardrailSummary.growth.raw_yearN
            : undefined;
    const baseGrowthGuardedYear1 =
        typeof valuationDiagnostics?.base_growth_guarded_year1 === 'number'
            ? valuationDiagnostics.base_growth_guarded_year1
            : typeof baseAssumptionGuardrailSummary?.growth?.guarded_year1 === 'number'
            ? baseAssumptionGuardrailSummary.growth.guarded_year1
            : undefined;
    const baseGrowthGuardedYearN =
        typeof valuationDiagnostics?.base_growth_guarded_yearN === 'number'
            ? valuationDiagnostics.base_growth_guarded_yearN
            : typeof baseAssumptionGuardrailSummary?.growth?.guarded_yearN === 'number'
            ? baseAssumptionGuardrailSummary.growth.guarded_yearN
            : undefined;
    const baseGrowthReasons = (baseAssumptionGuardrailSummary?.growth?.reasons ?? []).filter(
        (item): item is string => typeof item === 'string' && item.length > 0
    );
    const baseGrowthReasonsPreview = baseGrowthReasons.slice(0, 2);
    const baseGrowthReasonsOverflow = Math.max(
        0,
        baseGrowthReasons.length - baseGrowthReasonsPreview.length
    );
    const baseMarginGuardrailApplied =
        typeof valuationDiagnostics?.base_margin_guardrail_applied === 'boolean'
            ? valuationDiagnostics.base_margin_guardrail_applied
            : typeof baseAssumptionGuardrailSummary?.margin?.applied === 'boolean'
            ? baseAssumptionGuardrailSummary.margin.applied
            : undefined;
    const baseMarginGuardrailVersion =
        typeof valuationDiagnostics?.base_margin_guardrail_version === 'string' &&
        valuationDiagnostics.base_margin_guardrail_version.length > 0
            ? valuationDiagnostics.base_margin_guardrail_version
            : typeof baseAssumptionGuardrailSummary?.margin?.version === 'string' &&
                baseAssumptionGuardrailSummary.margin.version.length > 0
            ? baseAssumptionGuardrailSummary.margin.version
            : typeof baseAssumptionGuardrailSummary?.version === 'string' &&
                baseAssumptionGuardrailSummary.version.length > 0
            ? baseAssumptionGuardrailSummary.version
            : undefined;
    const baseMarginRawYear1 =
        typeof valuationDiagnostics?.base_margin_raw_year1 === 'number'
            ? valuationDiagnostics.base_margin_raw_year1
            : typeof baseAssumptionGuardrailSummary?.margin?.raw_year1 === 'number'
            ? baseAssumptionGuardrailSummary.margin.raw_year1
            : undefined;
    const baseMarginRawYearN =
        typeof valuationDiagnostics?.base_margin_raw_yearN === 'number'
            ? valuationDiagnostics.base_margin_raw_yearN
            : typeof baseAssumptionGuardrailSummary?.margin?.raw_yearN === 'number'
            ? baseAssumptionGuardrailSummary.margin.raw_yearN
            : undefined;
    const baseMarginGuardedYear1 =
        typeof valuationDiagnostics?.base_margin_guarded_year1 === 'number'
            ? valuationDiagnostics.base_margin_guarded_year1
            : typeof baseAssumptionGuardrailSummary?.margin?.guarded_year1 === 'number'
            ? baseAssumptionGuardrailSummary.margin.guarded_year1
            : undefined;
    const baseMarginGuardedYearN =
        typeof valuationDiagnostics?.base_margin_guarded_yearN === 'number'
            ? valuationDiagnostics.base_margin_guarded_yearN
            : typeof baseAssumptionGuardrailSummary?.margin?.guarded_yearN === 'number'
            ? baseAssumptionGuardrailSummary.margin.guarded_yearN
            : undefined;
    const baseMarginReasons = (baseAssumptionGuardrailSummary?.margin?.reasons ?? []).filter(
        (item): item is string => typeof item === 'string' && item.length > 0
    );
    const baseMarginReasonsPreview = baseMarginReasons.slice(0, 2);
    const baseMarginReasonsOverflow = Math.max(
        0,
        baseMarginReasons.length - baseMarginReasonsPreview.length
    );
    const hasBaseGrowthGuardrail =
        typeof baseGrowthGuardrailApplied === 'boolean' ||
        !!baseGrowthGuardrailVersion ||
        typeof baseGrowthRawYear1 === 'number' ||
        typeof baseGrowthRawYearN === 'number' ||
        typeof baseGrowthGuardedYear1 === 'number' ||
        typeof baseGrowthGuardedYearN === 'number' ||
        baseGrowthReasons.length > 0;
    const hasBaseMarginGuardrail =
        typeof baseMarginGuardrailApplied === 'boolean' ||
        !!baseMarginGuardrailVersion ||
        typeof baseMarginRawYear1 === 'number' ||
        typeof baseMarginRawYearN === 'number' ||
        typeof baseMarginGuardedYear1 === 'number' ||
        typeof baseMarginGuardedYearN === 'number' ||
        baseMarginReasons.length > 0;
    const sensitivityTopDrivers = (sensitivitySummary?.top_drivers ?? []).filter((item) => (
        item &&
        (typeof item.shock_dimension === 'string' ||
            typeof item.shock_value_bp === 'number' ||
            typeof item.delta_pct_vs_base === 'number')
    ));
    const sensitivityTopDriversPreview = sensitivityTopDrivers.slice(0, 2);
    const sensitivityTopDriversOverflow = Math.max(
        0,
        sensitivityTopDrivers.length - sensitivityTopDriversPreview.length
    );
    const equityValue = previewData?.equity_value;
    const intrinsicValue = previewData?.intrinsic_value;
    const upsidePotential = previewData?.upside_potential;
    const assumptionHighlights = useMemo(
        () => assumptionBreakdown?.assumptions?.slice(0, 2) ?? [],
        [assumptionBreakdown]
    );
    const assumptionHighlightsTotal = assumptionBreakdown?.assumptions?.length ?? 0;
    const assumptionHighlightsOverflow = Math.max(
        0,
        assumptionHighlightsTotal - assumptionHighlights.length
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
    const mcConverged = (() => {
        if (typeof monteCarloMeta?.converged === 'boolean') {
            return monteCarloMeta.converged;
        }
        return typeof distributionDiagnostics?.converged === 'boolean'
            ? distributionDiagnostics.converged
            : undefined;
    })();
    const mcMedianDelta = (() => {
        if (typeof monteCarloMeta?.median_delta === 'number') {
            return monteCarloMeta.median_delta;
        }
        return typeof distributionDiagnostics?.median_delta === 'number'
            ? distributionDiagnostics.median_delta
            : undefined;
    })();
    const mcTolerance = (() => {
        if (typeof monteCarloMeta?.tolerance === 'number') {
            return monteCarloMeta.tolerance;
        }
        return typeof distributionDiagnostics?.tolerance === 'number'
            ? distributionDiagnostics.tolerance
            : undefined;
    })();
    const mcSamplerType =
        typeof monteCarloMeta?.sampler_type === 'string'
            ? monteCarloMeta.sampler_type
            : undefined;
    const hasMonteCarloSummary =
        typeof monteCarloMeta?.enabled === 'boolean' ||
        mcExecutedIterations !== undefined ||
        mcEffectiveWindow !== undefined ||
        mcStoppedEarly !== undefined ||
        mcConfiguredIterations !== undefined ||
        mcConverged !== undefined ||
        mcMedianDelta !== undefined ||
        mcTolerance !== undefined ||
        mcSamplerType !== undefined;
    const mcPsdRepaired =
        typeof monteCarloMeta?.psd_repaired === 'boolean'
            ? monteCarloMeta.psd_repaired
            : undefined;
    const mcBatchEvaluatorUsed =
        typeof monteCarloMeta?.batch_evaluator_used === 'boolean'
            ? monteCarloMeta.batch_evaluator_used
            : undefined;
    const mcCorrDiagnosticsAvailable = monteCarloMeta?.corr_diagnostics_available === true;
    const mcCorrPairsTotal =
        typeof monteCarloMeta?.corr_pairs_total === 'number'
            ? monteCarloMeta.corr_pairs_total
            : undefined;
    const mcCorrPearsonMaxAbsError =
        typeof monteCarloMeta?.corr_pearson_max_abs_error === 'number'
            ? monteCarloMeta.corr_pearson_max_abs_error
            : undefined;
    const mcCorrSpearmanMaxAbsError =
        typeof monteCarloMeta?.corr_spearman_max_abs_error === 'number'
            ? monteCarloMeta.corr_spearman_max_abs_error
            : undefined;
    const mcCorrPearsonMae =
        typeof monteCarloMeta?.corr_pearson_mae === 'number'
            ? monteCarloMeta.corr_pearson_mae
            : undefined;
    const mcCorrSpearmanMae =
        typeof monteCarloMeta?.corr_spearman_mae === 'number'
            ? monteCarloMeta.corr_spearman_mae
            : undefined;
    const formatCorrError = (value: number | undefined): string | undefined => {
        if (typeof value !== 'number' || !Number.isFinite(value)) return undefined;
        return `${(value * 100).toFixed(1)}pp`;
    };
    const mcCorrPearsonMaxText = formatCorrError(mcCorrPearsonMaxAbsError);
    const mcCorrSpearmanMaxText = formatCorrError(mcCorrSpearmanMaxAbsError);
    const mcCorrPearsonMaeText = formatCorrError(mcCorrPearsonMae);
    const mcCorrSpearmanMaeText = formatCorrError(mcCorrSpearmanMae);
    const mcAsOf = dataFreshness?.market_data?.as_of;
    const assumptionRiskBadge = (() => {
        if (assumptionRiskLevel === 'high') {
            return {
                label: 'Risk: High',
                className: 'text-rose-200 border-rose-400/40 bg-rose-500/10',
            };
        }
        if (assumptionRiskLevel === 'medium') {
            return {
                label: 'Risk: Medium',
                className: 'text-amber-200 border-amber-400/40 bg-amber-500/10',
            };
        }
        if (assumptionRiskLevel === 'low') {
            return {
                label: 'Risk: Low',
                className: 'text-emerald-200 border-emerald-400/40 bg-emerald-500/10',
            };
        }
        return undefined;
    })();
    type SummaryItem = { label: string; value: string; tone?: string };
    const assumptionSummaryItems: SummaryItem[] = [];
    if (typeof monteCarloMeta?.enabled === 'boolean') {
        assumptionSummaryItems.push({
            label: 'Monte Carlo',
            value: monteCarloMeta.enabled ? 'Enabled' : 'Disabled',
            tone: monteCarloMeta.enabled ? 'text-emerald-200' : 'text-on-surface-variant',
        });
    }
    const forwardSignalSummaryValue = (() => {
        if (
            typeof forwardSignalSummary?.signals_total === 'number' &&
            typeof forwardSignalSummary?.signals_accepted === 'number'
        ) {
            return `${Math.round(forwardSignalSummary.signals_accepted)}/${Math.round(forwardSignalSummary.signals_total)} accepted`;
        }
        if (typeof forwardSignalEvidenceCount === 'number') {
            return `Evidence: ${Math.round(forwardSignalEvidenceCount)}`;
        }
        return null;
    })();
    if (forwardSignalSummaryValue) {
        const tone =
            forwardSignalRiskLevel === 'high'
                ? 'text-rose-200'
                : forwardSignalRiskLevel === 'medium'
                    ? 'text-amber-200'
                    : forwardSignalRiskLevel === 'low'
                        ? 'text-emerald-200'
                        : undefined;
        assumptionSummaryItems.push({
            label: 'Forward Signals',
            value: forwardSignalSummaryValue,
            tone,
        });
    }
    if (
        typeof sensitivitySummary?.enabled === 'boolean' ||
        typeof sensitivitySummary?.scenario_count === 'number'
    ) {
        const scenarioText =
            typeof sensitivitySummary?.scenario_count === 'number'
                ? `${Math.round(sensitivitySummary.scenario_count)} scenarios`
                : null;
        const statusText =
            typeof sensitivitySummary?.enabled === 'boolean'
                ? sensitivitySummary.enabled
                    ? 'On'
                    : 'Off'
                : 'On';
        assumptionSummaryItems.push({
            label: 'Sensitivity',
            value: `${statusText}${scenarioText ? ` · ${scenarioText}` : ''}`,
            tone: sensitivitySummary?.enabled ? 'text-emerald-200' : 'text-on-surface-variant',
        });
    }
    if (timeAlignmentStatus) {
        assumptionSummaryItems.push({
            label: 'Time Alignment',
            value: timeAlignmentStatus,
            tone:
                timeAlignmentStatus === 'high_risk' || timeAlignmentStatus === 'warning'
                    ? 'text-rose-200'
                    : 'text-emerald-200',
        });
    }
    const dataFreshnessItems = useMemo(() => {
        if (!dataFreshness) return [];
        const items: { label: string; value: string }[] = [];
        const pushItem = (
            label: string,
            value: string | number | null | undefined
        ) => {
            if (value === null || value === undefined || value === '') return;
            items.push({ label, value: String(value) });
        };
        pushItem(
            'Financial Period End',
            dataFreshness.financial_statement?.period_end_date
        );
        pushItem('Fiscal Year', dataFreshness.financial_statement?.fiscal_year);
        pushItem('Market Provider', dataFreshness.market_data?.provider);
        pushItem('Market As-Of', dataFreshness.market_data?.as_of);
        pushItem('Shares Source', dataFreshness.shares_outstanding_source);
        if (typeof dataFreshness.time_alignment?.lag_days === 'number') {
            const lagDays = Math.round(dataFreshness.time_alignment.lag_days);
            const threshold =
                typeof dataFreshness.time_alignment.threshold_days === 'number'
                    ? Math.round(dataFreshness.time_alignment.threshold_days)
                    : null;
            pushItem(
                'Time Alignment Lag',
                threshold !== null ? `${lagDays} days (threshold ${threshold} days)` : `${lagDays} days`
            );
        }
        pushItem('Time Alignment Policy', dataFreshness.time_alignment?.policy);
        return items;
    }, [dataFreshness]);
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
    function formatRatePercent(value: number): string {
        return `${(value * 100).toFixed(1)}%`;
    }
    function formatShockBp(value: number): string {
        return `${value >= 0 ? '+' : ''}${Math.round(value)}bp`;
    }
    function formatSignedBasisPoints(value: number): string {
        const rounded = Math.round(value * 10) / 10;
        return `${rounded >= 0 ? '+' : ''}${rounded.toFixed(1)} basis points`;
    }
    const formatSignalValue = (value: number, unit: 'basis_points' | 'ratio'): string => {
        if (unit === 'basis_points') {
            const rounded = Math.round(value * 10) / 10;
            return `${rounded >= 0 ? '+' : ''}${rounded.toFixed(1)} bps`;
        }
        return `${value >= 0 ? '+' : ''}${value.toFixed(3)}`;
    };
    const formatSignalMetric = (metric: string): string => {
        if (metric === 'growth_outlook') return 'Growth Outlook';
        if (metric === 'margin_outlook') return 'Margin Outlook';
        return metric.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
    };
    const formatSignalDate = (value: string | undefined): string => {
        if (!value) return 'N/A';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return value;
        return date.toISOString().slice(0, 10);
    };

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
        <div className="space-y-6 animate-fade-slide-up">
            <div className="flex items-center justify-between mb-6 px-2">
                <div className="flex items-center gap-3">
                    <LayoutPanelTop size={18} className="text-secondary" />
                    <h3 className="text-xs uppercase tracking-[0.2em] font-bold text-outline">Financial Data Matrix</h3>
                </div>
                <div className="flex items-center gap-2">
                    {modelTypeDisplay && (
                        <span className="rounded border border-outline-variant/10 bg-surface-container-low px-2 py-1 text-[11px] font-semibold text-primary-container">
                            Model: {modelTypeDisplay.label} ({modelTypeDisplay.code})
                        </span>
                    )}
                    {isReferenceLoading && (
                        <AgentLoadingState
                            type="header"
                            title="Loading Reports..."
                            colorClass="text-indigo-400"
                        />
                    )}
                </div>
            </div>

            {/* Preview Section - Valuation & Metrics */}
            {hasPreview && (
                <div className="space-y-4 animate-fade-slide-up">
                    {valuationScore !== undefined && (
                        <div className="bg-surface-container p-5 rounded-xl border border-outline-variant/10 flex items-center justify-between">
                            <span className="text-[10px] text-outline mb-2 block uppercase tracking-tighter">Analyst Valuation Score</span>
                            <div className="flex items-center gap-3">
                                <div className="h-1 w-24 bg-surface-container-high rounded-full overflow-hidden">
                                    <div
                                        className={`h-full transition-all duration-1000 ${valuationScore > 70 ? 'bg-emerald-500' : valuationScore < 40 ? 'bg-rose-500' : 'bg-amber-500'}`}
                                        style={{ width: `${valuationScore}%` }}
                                    />
                                </div>
                                <span className={`text-base font-black ${valuationScore > 70 ? 'text-emerald-400' : valuationScore < 40 ? 'text-rose-400' : 'text-amber-400'}`}>
                                    {Math.round(valuationScore)}/100
                                </span>
                            </div>
                        </div>
                    )}

                    {Object.keys(previewKeyMetrics).length > 0 && (
                        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                            {Object.entries(previewKeyMetrics).map(([label, value]) => (
                                <div key={label} className="bg-surface-container p-5 rounded-xl border border-outline-variant/10 hover:border-primary-container/30 transition-colors group">
                                    <div className="text-[10px] text-outline mb-2 block uppercase tracking-tighter group-hover:text-on-surface-variant transition-colors">{label}</div>
                                    <div className="text-lg font-black text-on-surface tabular-nums tracking-tight">
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
                                    className="bg-surface-container-low p-5 rounded-xl border border-outline-variant/10"
                                >
                                    <div className="text-[10px] text-outline mb-2 block uppercase tracking-tighter">{card.label}</div>
                                    <div
                                        className={`text-xl font-black ${
                                            card.unavailable
                                                ? 'text-on-surface-variant'
                                                : card.tone === 'bull'
                                                    ? 'text-emerald-300'
                                                    : card.tone === 'bear'
                                                        ? 'text-rose-300'
                                                        : 'text-on-surface'
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
                        <div className="grid grid-cols-1 gap-4 items-start">
                            {assumptionBreakdown && (
                                <div className="bg-surface-container p-5 rounded-xl border border-outline-variant/10 space-y-4">
                                    <div className="flex flex-wrap items-start justify-between gap-3">
                                        <div className="flex items-center gap-2">
                                            <span className="text-[10px] text-outline mb-2 block uppercase tracking-tighter">Assumption Breakdown</span>
                                            {assumptionRiskBadge && (
                                                <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${assumptionRiskBadge.className}`}>
                                                    {assumptionRiskBadge.label}
                                                </span>
                                            )}
                                        </div>
                                        <span className="text-xs font-semibold text-amber-300">
                                            {assumptionBreakdown.total_assumptions ?? 0} assumptions
                                        </span>
                                    </div>
                                    {assumptionSummaryItems.length > 0 && (
                                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                                            {assumptionSummaryItems.map((item) => (
                                                <div
                                                    key={item.label}
                                                    className="rounded-lg border border-outline-variant/20 bg-surface-container-low px-2 py-1"
                                                >
                                                    <div className="text-[10px] text-outline uppercase tracking-wider">
                                                        {item.label}
                                                    </div>
                                                    <div
                                                        className={`text-[11px] font-semibold ${item.tone ?? 'text-on-surface'}`}
                                                    >
                                                        {item.value}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                    {assumptionHighlights.length > 0 && (
                                        <div className="rounded-lg border border-outline-variant/20 bg-surface-container-low p-3 space-y-2">
                                            <div className="text-[11px] uppercase tracking-wider text-on-surface-variant">
                                                Assumption Highlights
                                            </div>
                                            <div className="space-y-2">
                                                {assumptionHighlights.map((item, index) => (
                                                    <div
                                                        key={`${item.statement}-${index}`}
                                                        className="text-xs text-on-surface bg-surface-container-high rounded px-2 py-1 break-words"
                                                    >
                                                        {item.statement}
                                                    </div>
                                                ))}
                                                {assumptionHighlightsOverflow > 0 && (
                                                    <div className="text-[11px] text-on-surface-variant">
                                                        +{assumptionHighlightsOverflow} more assumptions
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    )}
                                    <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                                        <div className="space-y-3">
                                            {hasMonteCarloSummary && (
                                                <div className="rounded-lg border border-outline-variant/20 bg-surface-container-low p-3 space-y-2">
                                                    <div className="flex items-center justify-between">
                                                        <div className="text-[11px] uppercase tracking-wider text-on-surface-variant">
                                                            Monte Carlo
                                                        </div>
                                                        {mcSamplerType && (
                                                            <span className="text-[11px] text-on-surface-variant">
                                                                Sampler: {mcSamplerType}
                                                            </span>
                                                        )}
                                                    </div>
                                                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                                                        {mcConfiguredIterations !== undefined && (
                                                            <div className="text-[11px] text-on-surface bg-surface-container-high rounded px-2 py-1">
                                                                Configured: {Math.round(mcConfiguredIterations)}
                                                            </div>
                                                        )}
                                                        {mcExecutedIterations !== undefined && (
                                                            <div className="text-[11px] text-on-surface bg-surface-container-high rounded px-2 py-1">
                                                                Executed: {Math.round(mcExecutedIterations)}
                                                            </div>
                                                        )}
                                                        {mcEffectiveWindow !== undefined && (
                                                            <div className="text-[11px] text-on-surface bg-surface-container-high rounded px-2 py-1">
                                                                Window: {Math.round(mcEffectiveWindow)}
                                                            </div>
                                                        )}
                                                        {mcStoppedEarly !== undefined && (
                                                            <div className="text-[11px] text-on-surface bg-surface-container-high rounded px-2 py-1">
                                                                Early Stop: {mcStoppedEarly ? 'Yes' : 'No'}
                                                            </div>
                                                        )}
                                                        {mcPsdRepaired !== undefined && (
                                                            <div className="text-[11px] text-on-surface bg-surface-container-high rounded px-2 py-1">
                                                                PSD Repair: {mcPsdRepaired ? 'Yes' : 'No'}
                                                            </div>
                                                        )}
                                                        {mcConverged !== undefined && (
                                                            <div className="text-[11px] text-on-surface bg-surface-container-high rounded px-2 py-1">
                                                                Converged: {mcConverged ? 'Yes' : 'No'}
                                                            </div>
                                                        )}
                                                        {mcMedianDelta !== undefined && (
                                                            <div className="text-[11px] text-on-surface bg-surface-container-high rounded px-2 py-1">
                                                                Median Δ: {(mcMedianDelta * 100).toFixed(2)}%
                                                                {mcTolerance !== undefined
                                                                    ? ` / ${(mcTolerance * 100).toFixed(2)}% tol`
                                                                    : ''}
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            )}
                                            {(forwardSignalSummary ||
                                                forwardSignalRiskLevel ||
                                                forwardSignalEvidenceCount !== undefined ||
                                                forwardSignalMappingVersion ||
                                                typeof forwardSignalCalibrationApplied === 'boolean') && (
                                                <div className="rounded-lg border border-outline-variant/20 bg-surface-container-low p-3 space-y-2">
                                                    <div className="text-[11px] uppercase tracking-wider text-on-surface-variant">
                                                        Forward Signal Policy
                                                    </div>
                                                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                                                        {typeof forwardSignalSummary?.signals_total === 'number' && (
                                                            <div className="text-[11px] text-on-surface bg-surface-container-high rounded px-2 py-1">
                                                                Signals: {Math.round(forwardSignalSummary.signals_total)}
                                                            </div>
                                                        )}
                                                        {typeof forwardSignalSummary?.signals_accepted === 'number' && (
                                                            <div className="text-[11px] text-emerald-200 bg-surface-container-high rounded px-2 py-1">
                                                                Accepted: {Math.round(forwardSignalSummary.signals_accepted)}
                                                            </div>
                                                        )}
                                                        {typeof forwardSignalSummary?.signals_rejected === 'number' && (
                                                            <div className="text-[11px] text-rose-200 bg-surface-container-high rounded px-2 py-1">
                                                                Rejected: {Math.round(forwardSignalSummary.signals_rejected)}
                                                            </div>
                                                        )}
                                                        {typeof forwardSignalEvidenceCount === 'number' && (
                                                            <div className="text-[11px] text-on-surface bg-surface-container-high rounded px-2 py-1">
                                                                Evidence: {Math.round(forwardSignalEvidenceCount)}
                                                            </div>
                                                        )}
                                                    </div>
                                                    {(typeof forwardSignalSummary?.growth_adjustment_basis_points === 'number' ||
                                                        typeof forwardSignalSummary?.margin_adjustment_basis_points === 'number') && (
                                                        <div className="flex flex-wrap gap-2">
                                                            {typeof forwardSignalSummary?.growth_adjustment_basis_points === 'number' && (
                                                                <span className="rounded border border-cyan-400/30 bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-200">
                                                                    Growth adjustment: {formatSignedBasisPoints(forwardSignalSummary.growth_adjustment_basis_points)}
                                                                </span>
                                                            )}
                                                            {typeof forwardSignalSummary?.margin_adjustment_basis_points === 'number' && (
                                                                <span className="rounded border border-cyan-400/30 bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-200">
                                                                    Margin adjustment: {formatSignedBasisPoints(forwardSignalSummary.margin_adjustment_basis_points)}
                                                                </span>
                                                            )}
                                                        </div>
                                                    )}
                                                    {(forwardSignalRiskLevel ||
                                                        forwardSignalSourceTypes.length > 0 ||
                                                        typeof forwardSignalCalibrationApplied === 'boolean') && (
                                                        <div className="flex flex-wrap items-center gap-2">
                                                            {forwardSignalRiskLevel && (
                                                                <span
                                                                    className={`rounded border border-outline-variant/10 px-2 py-0.5 text-[11px] ${
                                                                        forwardSignalRiskLevel === 'high'
                                                                            ? 'bg-rose-500/10 text-rose-200'
                                                                            : forwardSignalRiskLevel === 'medium'
                                                                                ? 'bg-amber-500/10 text-amber-200'
                                                                                : 'bg-emerald-500/10 text-emerald-200'
                                                                    }`}
                                                                >
                                                                    Forward Risk: {forwardSignalRiskLevel}
                                                                </span>
                                                            )}
                                                            {forwardSignalSourcePreview.map((source) => (
                                                                <span
                                                                    key={source}
                                                                    className="rounded bg-surface-container-high px-2 py-0.5 text-[11px] break-all max-w-full min-w-0"
                                                                >
                                                                    Source: {source}
                                                                </span>
                                                            ))}
                                                            {forwardSignalSourceOverflow > 0 && (
                                                                <span className="rounded bg-surface-container-high px-2 py-0.5 text-[11px] text-on-surface-variant">
                                                                    +{forwardSignalSourceOverflow} sources
                                                                </span>
                                                            )}
                                                            {typeof forwardSignalCalibrationApplied === 'boolean' && (
                                                                <span className="rounded border border-cyan-400/30 bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-200">
                                                                    Calibration: {forwardSignalCalibrationApplied ? 'Applied' : 'Bypassed'}
                                                                </span>
                                                            )}
                                                        </div>
                                                    )}
                                                    {forwardSignalMappingVersion && (
                                                        <div className="text-[11px] text-on-surface-variant break-all">
                                                            Mapping:{' '}
                                                            <span className="text-on-surface">
                                                                {forwardSignalMappingVersion}
                                                            </span>
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                            {sensitivitySummary && (
                                                <div className="rounded-lg border border-outline-variant/20 bg-surface-container-low p-3 space-y-2">
                                                    <div className="text-[11px] uppercase tracking-wider text-on-surface-variant">
                                                        Sensitivity (One-Way)
                                                    </div>
                                                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                                                        {typeof sensitivitySummary.enabled === 'boolean' && (
                                                            <div className="text-[11px] text-on-surface bg-surface-container-high rounded px-2 py-1">
                                                                Enabled: {sensitivitySummary.enabled ? 'Yes' : 'No'}
                                                            </div>
                                                        )}
                                                        {typeof sensitivitySummary.scenario_count === 'number' && (
                                                            <div className="text-[11px] text-on-surface bg-surface-container-high rounded px-2 py-1">
                                                                Scenarios: {Math.round(sensitivitySummary.scenario_count)}
                                                            </div>
                                                        )}
                                                        {typeof sensitivitySummary.max_upside_delta_pct === 'number' && (
                                                            <div className="text-[11px] text-emerald-200 bg-surface-container-high rounded px-2 py-1">
                                                                Max Upside: {formatPercent(sensitivitySummary.max_upside_delta_pct)}
                                                            </div>
                                                        )}
                                                        {typeof sensitivitySummary.max_downside_delta_pct === 'number' && (
                                                            <div className="text-[11px] text-rose-200 bg-surface-container-high rounded px-2 py-1">
                                                                Max Downside: {formatPercent(sensitivitySummary.max_downside_delta_pct)}
                                                            </div>
                                                        )}
                                                    </div>
                                                    {sensitivityTopDriversPreview.length > 0 && (
                                                        <div className="flex flex-wrap gap-2">
                                                            {sensitivityTopDriversPreview.map((driver, index) => (
                                                                <span
                                                                    key={`${driver.shock_dimension ?? 'driver'}-${driver.shock_value_bp ?? index}-${index}`}
                                                                    className="rounded border border-cyan-400/30 bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-200"
                                                                >
                                                                    {(driver.shock_dimension ?? 'driver').replace(/_/g, ' ')}{' '}
                                                                    {typeof driver.shock_value_bp === 'number'
                                                                        ? formatShockBp(driver.shock_value_bp)
                                                                        : ''}
                                                                    {typeof driver.delta_pct_vs_base === 'number'
                                                                        ? ` -> ${formatPercent(driver.delta_pct_vs_base)}`
                                                                        : ''}
                                                                </span>
                                                            ))}
                                                            {sensitivityTopDriversOverflow > 0 && (
                                                                <span className="rounded bg-surface-container-high px-2 py-0.5 text-[11px] text-on-surface-variant">
                                                                    +{sensitivityTopDriversOverflow} drivers
                                                                </span>
                                                            )}
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                        <div className="space-y-3">
                                            {(growthConsensusPolicyLabel ||
                                                growthConsensusHorizon ||
                                                terminalAnchorPolicyLabel ||
                                                typeof terminalAnchorStaleFallback === 'boolean' ||
                                                forwardSignalMappingVersion ||
                                                typeof forwardSignalCalibrationApplied === 'boolean') && (
                                                <div className="rounded-lg border border-outline-variant/20 bg-surface-container-low p-3 space-y-2">
                                                    <div className="text-[11px] uppercase tracking-wider text-on-surface-variant">
                                                        Growth / Anchor Policy
                                                    </div>
                                                    <div className="flex flex-wrap gap-2">
                                                        {growthConsensusPolicyLabel && (
                                                            <span className="rounded border border-indigo-400/30 bg-indigo-500/10 px-2 py-0.5 text-[11px] text-indigo-200">
                                                                Consensus: {growthConsensusPolicyLabel}
                                                            </span>
                                                        )}
                                                        {growthConsensusHorizon && (
                                                            <span className="rounded border border-indigo-400/30 bg-indigo-500/10 px-2 py-0.5 text-[11px] text-indigo-200">
                                                                Horizon: {growthConsensusHorizon}
                                                            </span>
                                                        )}
                                                        {terminalAnchorPolicyLabel && (
                                                            <span className="rounded border border-amber-400/30 bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-200">
                                                                Terminal Anchor: {terminalAnchorPolicyLabel}
                                                            </span>
                                                        )}
                                                        {typeof terminalAnchorStaleFallback === 'boolean' && (
                                                            <span className="rounded border border-amber-400/30 bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-200">
                                                                Stale Fallback: {terminalAnchorStaleFallback ? 'Yes' : 'No'}
                                                            </span>
                                                        )}
                                                    </div>
                                                    {(forwardSignalMappingVersion ||
                                                        typeof forwardSignalCalibrationApplied === 'boolean') && (
                                                        <div className="text-[11px] text-on-surface-variant">
                                                            {typeof forwardSignalCalibrationApplied === 'boolean' && (
                                                                <span>
                                                                    Calibration:{' '}
                                                                    <span className="text-on-surface">
                                                                        {forwardSignalCalibrationApplied ? 'Applied' : 'Bypassed'}
                                                                    </span>
                                                                </span>
                                                            )}
                                                            {forwardSignalMappingVersion && (
                                                                <span>
                                                                    {typeof forwardSignalCalibrationApplied === 'boolean'
                                                                        ? ' · '
                                                                        : ''}
                                                                    Mapping:{' '}
                                                                    <span className="text-on-surface">
                                                                        {forwardSignalMappingVersion}
                                                                    </span>
                                                                </span>
                                                            )}
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                            {(hasBaseGrowthGuardrail || hasBaseMarginGuardrail) && (
                                                <div className="rounded-lg border border-outline-variant/20 bg-surface-container-low p-3 space-y-2">
                                                    <div className="text-[11px] uppercase tracking-wider text-on-surface-variant">
                                                        Base Assumption Guardrail
                                                    </div>
                                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                                                        {hasBaseGrowthGuardrail && (
                                                            <div className="rounded border border-cyan-400/30 bg-cyan-500/10 px-2 py-2 text-[11px] text-cyan-100 space-y-1 min-w-0">
                                                                <div className="flex flex-wrap items-center justify-between gap-2">
                                                                    <span className="font-semibold">Growth</span>
                                                                    {typeof baseGrowthGuardrailApplied === 'boolean' && (
                                                                        <span className="text-[10px] uppercase tracking-wider">
                                                                            {baseGrowthGuardrailApplied ? 'Applied' : 'Bypassed'}
                                                                        </span>
                                                                    )}
                                                                </div>
                                                                {baseGrowthGuardrailVersion && (
                                                                    <div className="text-[10px] text-cyan-100/80 break-all">
                                                                        Version: {baseGrowthGuardrailVersion}
                                                                    </div>
                                                                )}
                                                                <div className="grid grid-cols-2 gap-1">
                                                                    {typeof baseGrowthRawYear1 === 'number' && (
                                                                        <div>Y1 Raw: {formatRatePercent(baseGrowthRawYear1)}</div>
                                                                    )}
                                                                    {typeof baseGrowthGuardedYear1 === 'number' && (
                                                                        <div>Y1 Guarded: {formatRatePercent(baseGrowthGuardedYear1)}</div>
                                                                    )}
                                                                    {typeof baseGrowthRawYearN === 'number' && (
                                                                        <div>YN Raw: {formatRatePercent(baseGrowthRawYearN)}</div>
                                                                    )}
                                                                    {typeof baseGrowthGuardedYearN === 'number' && (
                                                                        <div>YN Guarded: {formatRatePercent(baseGrowthGuardedYearN)}</div>
                                                                    )}
                                                                </div>
                                                                {baseGrowthReasonsPreview.length > 0 && (
                                                                    <div className="text-[10px] text-cyan-100/80 break-all">
                                                                        Reasons: {baseGrowthReasonsPreview.join(', ')}
                                                                        {baseGrowthReasonsOverflow > 0
                                                                            ? ` +${baseGrowthReasonsOverflow}`
                                                                            : ''}
                                                                    </div>
                                                                )}
                                                            </div>
                                                        )}
                                                        {hasBaseMarginGuardrail && (
                                                            <div className="rounded border border-amber-400/30 bg-amber-500/10 px-2 py-2 text-[11px] text-amber-100 space-y-1 min-w-0">
                                                                <div className="flex flex-wrap items-center justify-between gap-2">
                                                                    <span className="font-semibold">Margin</span>
                                                                    {typeof baseMarginGuardrailApplied === 'boolean' && (
                                                                        <span className="text-[10px] uppercase tracking-wider">
                                                                            {baseMarginGuardrailApplied ? 'Applied' : 'Bypassed'}
                                                                        </span>
                                                                    )}
                                                                </div>
                                                                {baseMarginGuardrailVersion && (
                                                                    <div className="text-[10px] text-amber-100/80 break-all">
                                                                        Version: {baseMarginGuardrailVersion}
                                                                    </div>
                                                                )}
                                                                <div className="grid grid-cols-2 gap-1">
                                                                    {typeof baseMarginRawYear1 === 'number' && (
                                                                        <div>Y1 Raw: {formatRatePercent(baseMarginRawYear1)}</div>
                                                                    )}
                                                                    {typeof baseMarginGuardedYear1 === 'number' && (
                                                                        <div>Y1 Guarded: {formatRatePercent(baseMarginGuardedYear1)}</div>
                                                                    )}
                                                                    {typeof baseMarginRawYearN === 'number' && (
                                                                        <div>YN Raw: {formatRatePercent(baseMarginRawYearN)}</div>
                                                                    )}
                                                                    {typeof baseMarginGuardedYearN === 'number' && (
                                                                        <div>YN Guarded: {formatRatePercent(baseMarginGuardedYearN)}</div>
                                                                    )}
                                                                </div>
                                                                {baseMarginReasonsPreview.length > 0 && (
                                                                    <div className="text-[10px] text-amber-100/80 break-all">
                                                                        Reasons: {baseMarginReasonsPreview.join(', ')}
                                                                        {baseMarginReasonsOverflow > 0
                                                                            ? ` +${baseMarginReasonsOverflow}`
                                                                            : ''}
                                                                    </div>
                                                                )}
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            )}
                                            {dataQualityFlagsPreview.length > 0 && (
                                                <div className="rounded-lg border border-outline-variant/20 bg-surface-container-low p-3 space-y-2">
                                                    <div className="text-[11px] uppercase tracking-wider text-on-surface-variant">
                                                        Data Quality Flags
                                                    </div>
                                                    <div className="flex flex-wrap gap-2">
                                                        {dataQualityFlagsPreview.map((flag) => (
                                                            <span
                                                                key={flag}
                                                                className="rounded border border-rose-400/30 bg-rose-500/10 px-2 py-0.5 text-[11px] text-rose-200 break-all max-w-full min-w-0"
                                                            >
                                                                {flag}
                                                            </span>
                                                        ))}
                                                        {dataQualityFlagsOverflow > 0 && (
                                                            <span className="rounded bg-surface-container-high px-2 py-0.5 text-[11px] text-on-surface-variant">
                                                                +{dataQualityFlagsOverflow} more
                                                            </span>
                                                        )}
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            )}

                            {dataFreshness && (
                                <div className="bg-surface-container p-5 rounded-xl border border-outline-variant/10 space-y-4">
                                    <div className="flex items-center justify-between">
                                        <span className="text-[10px] text-outline mb-2 block uppercase tracking-tighter">Data Freshness</span>
                                        {dataFreshness.time_alignment?.status && (
                                            <span
                                                className={`rounded border px-2 py-0.5 text-[11px] font-semibold ${
                                                    dataFreshness.time_alignment.status === 'high_risk' ||
                                                    dataFreshness.time_alignment.status === 'warning'
                                                        ? 'border-rose-400/40 bg-rose-500/10 text-rose-200'
                                                        : 'border-emerald-400/40 bg-emerald-500/10 text-emerald-200'
                                                }`}
                                            >
                                                Alignment: {dataFreshness.time_alignment.status}
                                            </span>
                                        )}
                                    </div>
                                    {dataFreshnessItems.length > 0 && (
                                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                            {dataFreshnessItems.map((item) => (
                                                <div
                                                    key={item.label}
                                                    className="rounded-lg border border-outline-variant/20 bg-surface-container-low px-3 py-2"
                                                >
                                                    <div className="text-[10px] text-outline uppercase tracking-wider">
                                                        {item.label}
                                                    </div>
                                                    <div className="text-sm font-semibold text-on-surface break-all">
                                                        {item.value}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    <ValuationDistributionSection
                        distributionSummary={distributionSummary}
                        distributionScenarios={distributionScenarios}
                        assumptionBreakdown={assumptionBreakdown}
                        intrinsicValue={intrinsicValue}
                        upsidePotential={upsidePotential}
                        mcSummary={{
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
                        }}
                    />
                </div>
            )}

            {forwardSignals.length > 0 && (
                <div className="bg-surface-container p-5 rounded-xl border border-outline-variant/10 space-y-4 flex flex-col">
                    <div className="flex items-center justify-between">
                        <span className="text-[10px] text-outline mb-2 block uppercase tracking-tighter">Forward Signals</span>
                        <span className="text-xs text-on-surface-variant">
                            {forwardSignals.length} extracted signals
                        </span>
                    </div>
                    <div className="space-y-4">
                        {forwardSignals.map((signal) => (
                            <div
                                key={signal.signal_id}
                                className="rounded-lg border border-outline-variant/30 bg-surface p-3 space-y-3"
                            >
                                <div className="flex flex-wrap items-center gap-2 justify-between">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <span className="text-sm font-semibold text-on-surface">
                                            {formatSignalMetric(signal.metric)}
                                        </span>
                                        <span
                                            className={`rounded border px-2 py-0.5 text-[11px] ${
                                                signal.direction === 'up'
                                                    ? 'border-emerald-400/40 bg-emerald-500/10 text-emerald-200'
                                                    : signal.direction === 'down'
                                                        ? 'border-rose-400/40 bg-rose-500/10 text-rose-200'
                                                        : 'border-slate-400/40 bg-slate-500/10 text-on-surface'
                                            }`}
                                        >
                                            {signal.direction.toUpperCase()}
                                        </span>
                                        <span className="rounded border border-indigo-400/30 bg-indigo-500/10 px-2 py-0.5 text-[11px] text-indigo-200">
                                            Source: {signal.source_type}
                                        </span>
                                    </div>
                                    <div className="flex flex-wrap items-center gap-3 text-xs text-on-surface">
                                        <span>Value: {formatSignalValue(signal.value, signal.unit)}</span>
                                        <span>
                                            Confidence: {(signal.confidence * 100).toFixed(1)}%
                                        </span>
                                        <span>As-of: {formatSignalDate(signal.as_of)}</span>
                                    </div>
                                </div>
                                <div className="overflow-x-auto rounded border border-outline-variant/30">
                                    <table className="w-full text-left text-xs">
                                        <thead className="bg-surface-container text-on-surface-variant">
                                            <tr>
                                                <th className="px-3 py-2 font-semibold">Evidence</th>
                                                <th className="px-3 py-2 font-semibold">Filing Date</th>
                                                <th className="px-3 py-2 font-semibold">Accession</th>
                                                <th className="px-3 py-2 font-semibold">Link</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {signal.evidence.map((item, index) => {
                                                const rowKey = `${signal.signal_id}-${item.accession_number ?? 'na'}-${index}`;
                                                const isExpanded = expandedEvidenceRows[rowKey] === true;
                                                const canExpand = item.full_text !== item.preview_text;
                                                const displayedText = isExpanded
                                                    ? item.full_text
                                                    : item.preview_text;
                                                return (
                                                <tr
                                                    key={rowKey}
                                                    className="border-t border-white/5 text-on-surface align-top"
                                                >
                                                    <td className="px-3 py-2 min-w-[360px]">
                                                        <div>{displayedText}</div>
                                                        {canExpand && (
                                                            <button
                                                                type="button"
                                                                className="mt-1 text-[11px] text-cyan-300 hover:text-cyan-200 underline"
                                                                onClick={() =>
                                                                    setExpandedEvidenceRows((current) => ({
                                                                        ...current,
                                                                        [rowKey]: !isExpanded,
                                                                    }))
                                                                }
                                                            >
                                                                {isExpanded ? 'Collapse' : 'Expand'}
                                                            </button>
                                                        )}
                                                        {(item.doc_type || item.period) && (
                                                            <div className="mt-1 text-[11px] text-on-surface-variant">
                                                                {[item.doc_type, item.period]
                                                                    .filter(Boolean)
                                                                    .join(' · ')}
                                                            </div>
                                                        )}
                                                    </td>
                                                    <td className="px-3 py-2 whitespace-nowrap">
                                                        {formatSignalDate(item.filing_date)}
                                                    </td>
                                                    <td className="px-3 py-2 whitespace-nowrap font-mono text-[11px]">
                                                        {item.accession_number ?? 'N/A'}
                                                    </td>
                                                    <td className="px-3 py-2 whitespace-nowrap">
                                                        <a
                                                            href={item.source_url}
                                                            target="_blank"
                                                            rel="noreferrer noopener"
                                                            className="inline-flex items-center gap-1 text-cyan-300 hover:text-cyan-200 underline"
                                                        >
                                                            Open Filing
                                                            <ExternalLink size={12} />
                                                        </a>
                                                    </td>
                                                </tr>
                                                );
                                            })}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        ))}
                    </div>
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
