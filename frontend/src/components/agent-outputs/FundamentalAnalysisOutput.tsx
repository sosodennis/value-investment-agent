import React, { memo, useMemo, useState } from 'react';
import { LayoutPanelTop, BarChart3, ChartArea, ExternalLink } from 'lucide-react';
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
import { ForwardSignal } from '@/types/agents/fundamental';
import { ParsedFinancialPreview } from '@/types/agents/fundamental-preview-parser';
import { useArtifact } from '../../hooks/useArtifact';
import { AgentLoadingState } from './AgentLoadingState';

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
    const valuationDiagnostics =
        previewData?.valuation_diagnostics ?? artifactData?.valuation_diagnostics;
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
    const mcEnabled = monteCarloMeta?.enabled === true;
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
                <div className="flex items-center gap-2">
                    {modelTypeDisplay && (
                        <span className="rounded border border-indigo-400/30 bg-indigo-500/10 px-2 py-1 text-[11px] font-semibold text-indigo-200">
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
                                        <div className="flex items-center gap-2">
                                            {assumptionRiskBadge && (
                                                <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${assumptionRiskBadge.className}`}>
                                                    {assumptionRiskBadge.label}
                                                </span>
                                            )}
                                            <span className="text-xs font-semibold text-amber-300">
                                                {assumptionBreakdown.total_assumptions ?? 0} assumptions
                                            </span>
                                        </div>
                                    </div>
                                    {typeof assumptionBreakdown.monte_carlo?.enabled === 'boolean' && (
                                        <div className="text-xs text-slate-300">
                                            Monte Carlo: {assumptionBreakdown.monte_carlo.enabled ? 'Enabled' : 'Disabled'}
                                            {mcSamplerType ? ` (${mcSamplerType})` : ''}
                                        </div>
                                    )}
                                    {mcEnabled && (
                                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-2">
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
                                            {mcPsdRepaired !== undefined && (
                                                <div className="text-[11px] text-slate-200 bg-slate-900/40 rounded px-2 py-1">
                                                    PSD Repair: {mcPsdRepaired ? 'Yes' : 'No'}
                                                </div>
                                            )}
                                            {mcConverged !== undefined && (
                                                <div className="text-[11px] text-slate-200 bg-slate-900/40 rounded px-2 py-1">
                                                    Converged: {mcConverged ? 'Yes' : 'No'}
                                                </div>
                                            )}
                                            {mcMedianDelta !== undefined && (
                                                <div className="text-[11px] text-slate-200 bg-slate-900/40 rounded px-2 py-1">
                                                    Median Δ: {(mcMedianDelta * 100).toFixed(2)}%
                                                    {mcTolerance !== undefined
                                                        ? ` / ${(mcTolerance * 100).toFixed(2)}% tol`
                                                        : ''}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                    {(forwardSignalSummary ||
                                        forwardSignalRiskLevel ||
                                        forwardSignalEvidenceCount !== undefined ||
                                        forwardSignalMappingVersion ||
                                        typeof forwardSignalCalibrationApplied === 'boolean') && (
                                        <div className="space-y-2">
                                            <div className="text-[11px] uppercase tracking-wider text-slate-400">
                                                Forward Signal Policy
                                            </div>
                                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                                                {typeof forwardSignalSummary?.signals_total === 'number' && (
                                                    <div className="text-[11px] text-slate-200 bg-slate-900/40 rounded px-2 py-1">
                                                        Signals: {Math.round(forwardSignalSummary.signals_total)}
                                                    </div>
                                                )}
                                                {typeof forwardSignalSummary?.signals_accepted === 'number' && (
                                                    <div className="text-[11px] text-emerald-200 bg-slate-900/40 rounded px-2 py-1">
                                                        Accepted: {Math.round(forwardSignalSummary.signals_accepted)}
                                                    </div>
                                                )}
                                                {typeof forwardSignalSummary?.signals_rejected === 'number' && (
                                                    <div className="text-[11px] text-rose-200 bg-slate-900/40 rounded px-2 py-1">
                                                        Rejected: {Math.round(forwardSignalSummary.signals_rejected)}
                                                    </div>
                                                )}
                                                {typeof forwardSignalEvidenceCount === 'number' && (
                                                    <div className="text-[11px] text-slate-200 bg-slate-900/40 rounded px-2 py-1">
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
                                                forwardSignalMappingVersion ||
                                                typeof forwardSignalCalibrationApplied === 'boolean') && (
                                                <div className="flex flex-wrap items-center gap-2">
                                                    {forwardSignalRiskLevel && (
                                                        <span
                                                            className={`rounded border px-2 py-0.5 text-[11px] ${
                                                                forwardSignalRiskLevel === 'high'
                                                                    ? 'border-rose-400/40 bg-rose-500/10 text-rose-200'
                                                                    : forwardSignalRiskLevel === 'medium'
                                                                        ? 'border-amber-400/40 bg-amber-500/10 text-amber-200'
                                                                        : 'border-emerald-400/40 bg-emerald-500/10 text-emerald-200'
                                                            }`}
                                                        >
                                                            Forward Risk: {forwardSignalRiskLevel}
                                                        </span>
                                                    )}
                                                    {forwardSignalSourceTypes.map((source) => (
                                                        <span
                                                            key={source}
                                                            className="rounded border border-indigo-400/30 bg-indigo-500/10 px-2 py-0.5 text-[11px] text-indigo-200"
                                                        >
                                                            Source: {source}
                                                        </span>
                                                    ))}
                                                    {typeof forwardSignalCalibrationApplied === 'boolean' && (
                                                        <span className="rounded border border-cyan-400/30 bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-200">
                                                            Calibration: {forwardSignalCalibrationApplied ? 'Applied' : 'Bypassed'}
                                                        </span>
                                                    )}
                                                    {forwardSignalMappingVersion && (
                                                        <span className="rounded border border-slate-400/30 bg-slate-800/60 px-2 py-0.5 text-[11px] text-slate-200">
                                                            Mapping: {forwardSignalMappingVersion}
                                                        </span>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                    {sensitivitySummary && (
                                        <div className="space-y-2">
                                            <div className="text-[11px] uppercase tracking-wider text-slate-400">
                                                Sensitivity (One-Way)
                                            </div>
                                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                                                {typeof sensitivitySummary.enabled === 'boolean' && (
                                                    <div className="text-[11px] text-slate-200 bg-slate-900/40 rounded px-2 py-1">
                                                        Enabled: {sensitivitySummary.enabled ? 'Yes' : 'No'}
                                                    </div>
                                                )}
                                                {typeof sensitivitySummary.scenario_count === 'number' && (
                                                    <div className="text-[11px] text-slate-200 bg-slate-900/40 rounded px-2 py-1">
                                                        Scenarios: {Math.round(sensitivitySummary.scenario_count)}
                                                    </div>
                                                )}
                                                {typeof sensitivitySummary.max_upside_delta_pct === 'number' && (
                                                    <div className="text-[11px] text-emerald-200 bg-slate-900/40 rounded px-2 py-1">
                                                        Max Upside: {formatPercent(sensitivitySummary.max_upside_delta_pct)}
                                                    </div>
                                                )}
                                                {typeof sensitivitySummary.max_downside_delta_pct === 'number' && (
                                                    <div className="text-[11px] text-rose-200 bg-slate-900/40 rounded px-2 py-1">
                                                        Max Downside: {formatPercent(sensitivitySummary.max_downside_delta_pct)}
                                                    </div>
                                                )}
                                            </div>
                                            {sensitivityTopDrivers.length > 0 && (
                                                <div className="flex flex-wrap gap-2">
                                                    {sensitivityTopDrivers.slice(0, 3).map((driver, index) => (
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
                                                </div>
                                            )}
                                        </div>
                                    )}
                                    {(growthConsensusPolicyLabel ||
                                        growthConsensusHorizon ||
                                        terminalAnchorPolicyLabel ||
                                        typeof terminalAnchorStaleFallback === 'boolean' ||
                                        forwardSignalMappingVersion ||
                                        typeof forwardSignalCalibrationApplied === 'boolean') && (
                                        <div className="space-y-2">
                                            <div className="text-[11px] uppercase tracking-wider text-slate-400">
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
                                                <div className="space-y-1 text-[11px] text-slate-300">
                                                    {typeof forwardSignalCalibrationApplied === 'boolean' && (
                                                        <div>
                                                            Calibration Applied (Diagnostics):{' '}
                                                            <span className="font-semibold text-slate-100">
                                                                {forwardSignalCalibrationApplied ? 'Yes' : 'No'}
                                                            </span>
                                                        </div>
                                                    )}
                                                    {forwardSignalMappingVersion && (
                                                        <div>
                                                            Calibration Mapping (Diagnostics):{' '}
                                                            <span className="font-semibold text-slate-100">
                                                                {forwardSignalMappingVersion}
                                                            </span>
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                    {(hasBaseGrowthGuardrail || hasBaseMarginGuardrail) && (
                                        <div className="space-y-2">
                                            <div className="text-[11px] uppercase tracking-wider text-slate-400">
                                                Base Assumption Guardrail
                                            </div>
                                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                                {hasBaseGrowthGuardrail && (
                                                    <div className="rounded border border-cyan-400/30 bg-cyan-500/10 px-2 py-1 text-[11px] text-cyan-100 space-y-1">
                                                        {typeof baseGrowthGuardrailApplied === 'boolean' && (
                                                            <div>Growth: {baseGrowthGuardrailApplied ? 'Applied' : 'Bypassed'}</div>
                                                        )}
                                                        {baseGrowthGuardrailVersion && (
                                                            <div>Growth Version: {baseGrowthGuardrailVersion}</div>
                                                        )}
                                                        {typeof baseGrowthRawYear1 === 'number' && (
                                                            <div>Growth Y1 Raw: {formatRatePercent(baseGrowthRawYear1)}</div>
                                                        )}
                                                        {typeof baseGrowthGuardedYear1 === 'number' && (
                                                            <div>Growth Y1 Guarded: {formatRatePercent(baseGrowthGuardedYear1)}</div>
                                                        )}
                                                        {typeof baseGrowthRawYearN === 'number' && (
                                                            <div>Growth YN Raw: {formatRatePercent(baseGrowthRawYearN)}</div>
                                                        )}
                                                        {typeof baseGrowthGuardedYearN === 'number' && (
                                                            <div>Growth YN Guarded: {formatRatePercent(baseGrowthGuardedYearN)}</div>
                                                        )}
                                                        {baseGrowthReasons.length > 0 && (
                                                            <div>Growth Reasons: {baseGrowthReasons.join(', ')}</div>
                                                        )}
                                                    </div>
                                                )}
                                                {hasBaseMarginGuardrail && (
                                                    <div className="rounded border border-amber-400/30 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-100 space-y-1">
                                                        {typeof baseMarginGuardrailApplied === 'boolean' && (
                                                            <div>Margin: {baseMarginGuardrailApplied ? 'Applied' : 'Bypassed'}</div>
                                                        )}
                                                        {baseMarginGuardrailVersion && (
                                                            <div>Margin Version: {baseMarginGuardrailVersion}</div>
                                                        )}
                                                        {typeof baseMarginRawYear1 === 'number' && (
                                                            <div>Margin Y1 Raw: {formatRatePercent(baseMarginRawYear1)}</div>
                                                        )}
                                                        {typeof baseMarginGuardedYear1 === 'number' && (
                                                            <div>Margin Y1 Guarded: {formatRatePercent(baseMarginGuardedYear1)}</div>
                                                        )}
                                                        {typeof baseMarginRawYearN === 'number' && (
                                                            <div>Margin YN Raw: {formatRatePercent(baseMarginRawYearN)}</div>
                                                        )}
                                                        {typeof baseMarginGuardedYearN === 'number' && (
                                                            <div>Margin YN Guarded: {formatRatePercent(baseMarginGuardedYearN)}</div>
                                                        )}
                                                        {baseMarginReasons.length > 0 && (
                                                            <div>Margin Reasons: {baseMarginReasons.join(', ')}</div>
                                                        )}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    )}
                                    {dataQualityFlags.length > 0 && (
                                        <div className="space-y-2">
                                            <div className="text-[11px] uppercase tracking-wider text-slate-400">
                                                Data Quality Flags
                                            </div>
                                            <div className="flex flex-wrap gap-2">
                                                {dataQualityFlags.map((flag) => (
                                                    <span
                                                        key={flag}
                                                        className="rounded border border-rose-400/30 bg-rose-500/10 px-2 py-0.5 text-[11px] text-rose-200"
                                                    >
                                                        {flag}
                                                    </span>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                    {timeAlignmentStatus && (
                                        <div className="text-[11px] text-slate-300">
                                            Time Alignment Status:{' '}
                                            <span
                                                className={
                                                    timeAlignmentStatus === 'high_risk' || timeAlignmentStatus === 'warning'
                                                        ? 'text-rose-300 font-semibold'
                                                        : 'text-emerald-300 font-semibold'
                                                }
                                            >
                                                {timeAlignmentStatus}
                                            </span>
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
                    )}
                </div>
            )}

            {forwardSignals.length > 0 && (
                <div className="tech-card p-4 space-y-4 border-cyan-500/25 bg-gradient-to-br from-cyan-950/20 via-slate-900/40 to-slate-950/20">
                    <div className="flex items-center justify-between">
                        <span className="text-label">Forward Signals</span>
                        <span className="text-xs text-slate-300">
                            {forwardSignals.length} extracted signals
                        </span>
                    </div>
                    <div className="space-y-4">
                        {forwardSignals.map((signal) => (
                            <div
                                key={signal.signal_id}
                                className="rounded-lg border border-white/10 bg-slate-950/50 p-3 space-y-3"
                            >
                                <div className="flex flex-wrap items-center gap-2 justify-between">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <span className="text-sm font-semibold text-white">
                                            {formatSignalMetric(signal.metric)}
                                        </span>
                                        <span
                                            className={`rounded border px-2 py-0.5 text-[11px] ${
                                                signal.direction === 'up'
                                                    ? 'border-emerald-400/40 bg-emerald-500/10 text-emerald-200'
                                                    : signal.direction === 'down'
                                                        ? 'border-rose-400/40 bg-rose-500/10 text-rose-200'
                                                        : 'border-slate-400/40 bg-slate-500/10 text-slate-200'
                                            }`}
                                        >
                                            {signal.direction.toUpperCase()}
                                        </span>
                                        <span className="rounded border border-indigo-400/30 bg-indigo-500/10 px-2 py-0.5 text-[11px] text-indigo-200">
                                            Source: {signal.source_type}
                                        </span>
                                    </div>
                                    <div className="flex flex-wrap items-center gap-3 text-xs text-slate-200">
                                        <span>Value: {formatSignalValue(signal.value, signal.unit)}</span>
                                        <span>
                                            Confidence: {(signal.confidence * 100).toFixed(1)}%
                                        </span>
                                        <span>As-of: {formatSignalDate(signal.as_of)}</span>
                                    </div>
                                </div>
                                <div className="overflow-x-auto rounded border border-white/10">
                                    <table className="w-full text-left text-xs">
                                        <thead className="bg-slate-900/70 text-slate-300">
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
                                                    className="border-t border-white/5 text-slate-200 align-top"
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
                                                            <div className="mt-1 text-[11px] text-slate-400">
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
