import React from 'react';
import { Bell, ChevronDown, Layers } from 'lucide-react';
import type {
    AlertSeverity,
    TechnicalAlertSignal,
    TechnicalAlertsArtifact,
    TechnicalDirectionScorecard,
    TechnicalFeatureIndicator,
    TechnicalFeaturePack,
    TechnicalFusionReport,
    TechnicalPatternFlag,
    TechnicalPatternLevel,
    TechnicalPatternPack,
    TechnicalScorecardContribution,
    TechnicalScorecardFrame,
    TechnicalVerificationReport,
} from '@/types/agents/technical';
import { AgentLoadingState } from '../shared/AgentLoadingState';

type AlertTone = { label: string; badge: string };

type AlertsSummary = {
    total: number;
    severityCounts: { critical: number; warning: number; info: number };
    generatedAt: string | null;
    alerts: TechnicalAlertSignal[];
};

type FeaturePackFrameSummary = {
    timeframe: string;
    classicCount: number;
    quantCount: number;
    classicHighlights: TechnicalFeatureIndicator[];
    quantHighlights: TechnicalFeatureIndicator[];
};

type FeaturePackSummary = {
    summaries: FeaturePackFrameSummary[];
    classicTotal: number;
    quantTotal: number;
};

type PatternPackFrameSummary = {
    timeframe: string;
    supportCount: number;
    resistanceCount: number;
    breakoutCount: number;
    trendCount: number;
    flagCount: number;
    supportLevels: TechnicalPatternLevel[];
    resistanceLevels: TechnicalPatternLevel[];
    breakoutFlags: TechnicalPatternFlag[];
    trendFlags: TechnicalPatternFlag[];
};

type PatternPackSummary = {
    summaries: PatternPackFrameSummary[];
    totalLevels: number;
    totalFlags: number;
};

type FusionReportEntry = {
    timeframe: string;
    classic: string;
    quant: string;
    pattern: string;
    classicScore: number | null;
    quantScore: number | null;
    patternScore: number | null;
};

type FusionReportSummary = {
    entries: FusionReportEntry[];
    totalFrames: number;
};

type ScorecardSummaryEntry = {
    timeframe: string;
    frame: TechnicalScorecardFrame;
};

type ScorecardSummary = {
    entries: ScorecardSummaryEntry[];
    modelVersion: string | null;
    overallScore: number;
    neutralThreshold: number;
};

type VerificationSummary = {
    gatesCount: number;
    flagsCount: number;
};

export interface TechnicalAnalysisSupplementarySectionProps {
    alertsId: string | null;
    alertsData?: TechnicalAlertsArtifact | null;
    alertsSummary: AlertsSummary | null;
    alertsError?: Error | null;
    isAlertsLoadingState: boolean;
    showAlerts: boolean;
    setShowAlerts: React.Dispatch<React.SetStateAction<boolean>>;
    featurePackId: string | null;
    featurePackData?: TechnicalFeaturePack | null;
    featurePackSummary: FeaturePackSummary | null;
    featurePackError?: Error | null;
    isFeaturePackLoading: boolean;
    showFeaturePack: boolean;
    setShowFeaturePack: React.Dispatch<React.SetStateAction<boolean>>;
    patternPackId: string | null;
    patternPackData?: TechnicalPatternPack | null;
    patternPackSummary: PatternPackSummary | null;
    patternPackError?: Error | null;
    isPatternPackLoading: boolean;
    showPatternPack: boolean;
    setShowPatternPack: React.Dispatch<React.SetStateAction<boolean>>;
    fusionReportId: string | null;
    fusionReportData?: TechnicalFusionReport | null;
    fusionReportSummary: FusionReportSummary | null;
    fusionReportError?: Error | null;
    isFusionReportLoading: boolean;
    fusionConfidenceDisplay: string;
    fusionConfidenceLabel: string;
    fusionRawDisplay: string | null;
    showFusionReport: boolean;
    setShowFusionReport: React.Dispatch<React.SetStateAction<boolean>>;
    directionScorecardData?: TechnicalDirectionScorecard | null;
    scorecardSummary: ScorecardSummary | null;
    directionScorecardError?: Error | null;
    isDirectionScorecardLoading: boolean;
    verificationReportId: string | null;
    verificationReportData?: TechnicalVerificationReport | null;
    verificationSummary: VerificationSummary | null;
    verificationReportError?: Error | null;
    isVerificationReportLoading: boolean;
    showVerificationReport: boolean;
    setShowVerificationReport: React.Dispatch<React.SetStateAction<boolean>>;
    artifactEntries: Array<[string, string]>;
    getAlertSeverityTone: (severity: AlertSeverity) => AlertTone;
    formatLabel: (value: string) => string;
    formatIndicatorValue: (value: number | null | undefined) => string;
    formatContributionValue: (value: number | null | undefined) => string;
    formatPrice: (value: number) => string;
    formatConfidence: (value: number | null | undefined) => string;
    formatArtifactLabel: (value: string) => string;
    formatArtifactId: (value: string) => string;
    renderIndicatorHighlights: (
        indicators: TechnicalFeaturePack['timeframes'][string]['classic_indicators'][string][]
    ) => React.ReactNode;
    renderScorecardContributions: (
        items: TechnicalScorecardContribution[]
    ) => React.ReactNode;
};

export const TechnicalAnalysisSupplementarySection: React.FC<TechnicalAnalysisSupplementarySectionProps> = ({
    alertsId,
    alertsData,
    alertsSummary,
    alertsError,
    isAlertsLoadingState,
    showAlerts,
    setShowAlerts,
    featurePackId,
    featurePackData,
    featurePackSummary,
    featurePackError,
    isFeaturePackLoading,
    showFeaturePack,
    setShowFeaturePack,
    patternPackId,
    patternPackData,
    patternPackSummary,
    patternPackError,
    isPatternPackLoading,
    showPatternPack,
    setShowPatternPack,
    fusionReportId,
    fusionReportData,
    fusionReportSummary,
    fusionReportError,
    isFusionReportLoading,
    fusionConfidenceDisplay,
    fusionConfidenceLabel,
    fusionRawDisplay,
    showFusionReport,
    setShowFusionReport,
    directionScorecardData,
    scorecardSummary,
    directionScorecardError,
    isDirectionScorecardLoading,
    verificationReportId,
    verificationReportData,
    verificationSummary,
    verificationReportError,
    isVerificationReportLoading,
    showVerificationReport,
    setShowVerificationReport,
    artifactEntries,
    getAlertSeverityTone,
    formatLabel,
    formatIndicatorValue,
    formatContributionValue,
    formatPrice,
    formatConfidence,
    formatArtifactLabel,
    formatArtifactId,
    renderIndicatorHighlights,
    renderScorecardContributions,
}) => (
    <section className="space-y-4">
        <div className="flex items-center gap-2">
            <Layers size={14} className="text-cyan-400 opacity-70" />
            <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">Other</span>
        </div>

        {alertsId && (
            <section className="rounded-xl border border-outline-variant/10 bg-surface-container overflow-hidden transition-colors duration-300">
                <button
                    onClick={() => setShowAlerts(!showAlerts)}
                    className="w-full flex items-center justify-between p-4 bg-surface-container-low hover:bg-surface-container-low transition-colors"
                >
                    <div className="flex items-center gap-2">
                        <Bell size={14} className="text-outline" />
                        <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">Alert Signals</span>
                    </div>
                    <div className="flex items-center gap-4">
                        {showAlerts && isAlertsLoadingState && (
                            <AgentLoadingState
                                type="header"
                                title="Loading Alerts…"
                                colorClass="text-cyan-400"
                            />
                        )}
                        {alertsSummary && (
                            <div className="flex items-center gap-2 text-[9px] font-bold uppercase text-outline">
                                <span>Total {alertsSummary.total}</span>
                                <span className="text-rose-300">C {alertsSummary.severityCounts.critical}</span>
                                <span className="text-amber-300">W {alertsSummary.severityCounts.warning}</span>
                                <span className="text-on-surface-variant">I {alertsSummary.severityCounts.info}</span>
                            </div>
                        )}
                        <ChevronDown
                            size={16}
                            className={`text-outline expandable-chevron ${showAlerts ? 'rotate-180' : ''}`}
                        />
                    </div>
                </button>

                <div
                    className={`expandable-panel ${
                        showAlerts ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                    }`}
                >
                    <div className="overflow-hidden">
                        <div className="p-6 space-y-5">
                            {alertsError && (
                                <div className="text-xs text-rose-300">
                                    Unable to load alerts. Please retry later.
                                </div>
                            )}

                            {!alertsData && !alertsError && (
                                <div className="text-xs text-outline">
                                    Alert data will appear here once loaded.
                                </div>
                            )}

                            {alertsData && alertsSummary && (
                                <>
                                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                                        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-1">Total Alerts</div>
                                            <div className="text-lg font-black text-on-surface">{alertsSummary.total}</div>
                                        </div>
                                        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-1">Critical</div>
                                            <div className="text-lg font-black text-rose-300">{alertsSummary.severityCounts.critical}</div>
                                        </div>
                                        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-1">Warning</div>
                                            <div className="text-lg font-black text-amber-300">{alertsSummary.severityCounts.warning}</div>
                                        </div>
                                        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-1">Info</div>
                                            <div className="text-lg font-black text-on-surface">{alertsSummary.severityCounts.info}</div>
                                        </div>
                                    </div>

                                    {alertsSummary.generatedAt && (
                                        <div className="text-[10px] text-outline">
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
                                                        className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20 space-y-3"
                                                    >
                                                        <div className="flex items-start justify-between gap-4">
                                                            <div>
                                                                <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-outline mb-1">
                                                                    {alert.timeframe.toUpperCase()} · {formatLabel(alert.code)}
                                                                </div>
                                                                <div className="text-sm font-black text-on-surface">{alert.title}</div>
                                                                {alert.message && (
                                                                    <div className="text-xs text-on-surface-variant mt-1">
                                                                        {alert.message}
                                                                    </div>
                                                                )}
                                                            </div>
                                                            <span
                                                                className={`px-2.5 py-1 rounded-full border text-[9px] font-black uppercase tracking-[0.2em] ${tone.badge}`}
                                                            >
                                                                {tone.label}
                                                            </span>
                                                        </div>
                                                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-[10px] text-on-surface-variant">
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
                                        <div className="text-xs text-outline">
                                            No Alert Signals Detected For The Current Window
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    </div>
                </div>
            </section>
        )}

        {featurePackId && (
            <section className="rounded-xl border border-outline-variant/10 bg-surface-container overflow-hidden transition-colors duration-300">
                <button
                    onClick={() => setShowFeaturePack(!showFeaturePack)}
                    className="w-full flex items-center justify-between p-4 bg-surface-container-low hover:bg-surface-container-low transition-colors"
                >
                    <div className="flex items-center gap-2">
                        <Layers size={14} className="text-outline" />
                        <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">Feature Pack</span>
                    </div>
                    <div className="flex items-center gap-4">
                        {showFeaturePack && isFeaturePackLoading && (
                            <AgentLoadingState
                                type="header"
                                title="Loading Feature Pack…"
                                colorClass="text-cyan-400"
                            />
                        )}
                        <ChevronDown
                            size={16}
                            className={`text-outline expandable-chevron ${showFeaturePack ? 'rotate-180' : ''}`}
                        />
                    </div>
                </button>

                <div
                    className={`expandable-panel ${
                        showFeaturePack ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                    }`}
                >
                    <div className="overflow-hidden">
                        <div className="p-6 space-y-5">
                            {featurePackError && (
                                <div className="text-xs text-rose-300">
                                    Unable to load feature pack. Please retry later.
                                </div>
                            )}

                            {!featurePackData && !featurePackError && (
                                <div className="text-xs text-outline">
                                    Feature pack data will appear here once loaded.
                                </div>
                            )}

                            {featurePackData && featurePackSummary && (
                                <>
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-1">Timeframes</div>
                                            <div className="text-lg font-black text-on-surface">{featurePackSummary.summaries.length}</div>
                                        </div>
                                        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-1">Classic Indicators</div>
                                            <div className="text-lg font-black text-on-surface">{featurePackSummary.classicTotal}</div>
                                        </div>
                                        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-1">Quant Features</div>
                                            <div className="text-lg font-black text-on-surface">{featurePackSummary.quantTotal}</div>
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
                                            <div key={frame.timeframe} className="bg-surface-container-low p-5 rounded-xl border border-outline-variant/20 space-y-3">
                                                <div className="flex items-center justify-between">
                                                    <div className="text-xs font-black uppercase tracking-[0.2em] text-on-surface-variant">
                                                        {formatLabel(frame.timeframe)}
                                                    </div>
                                                    <div className="text-[10px] text-outline font-bold uppercase">
                                                        Classic {frame.classicCount} · Quant {frame.quantCount}
                                                    </div>
                                                </div>
                                                <div>
                                                    <div className="text-[9px] font-bold text-outline uppercase mb-2">Classic Highlights</div>
                                                    {renderIndicatorHighlights(frame.classicHighlights)}
                                                </div>
                                                <div>
                                                    <div className="text-[9px] font-bold text-outline uppercase mb-2">Quant Highlights</div>
                                                    {renderIndicatorHighlights(frame.quantHighlights)}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                </div>
            </section>
        )}

        {patternPackId && (
            <section className="rounded-xl border border-outline-variant/10 bg-surface-container overflow-hidden transition-colors duration-300">
                <button
                    onClick={() => setShowPatternPack(!showPatternPack)}
                    className="w-full flex items-center justify-between p-4 bg-surface-container-low hover:bg-surface-container-low transition-colors"
                >
                    <div className="flex items-center gap-2">
                        <Layers size={14} className="text-outline" />
                        <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">Pattern Pack</span>
                    </div>
                    <div className="flex items-center gap-4">
                        {showPatternPack && isPatternPackLoading && (
                            <AgentLoadingState
                                type="header"
                                title="Loading Pattern Pack…"
                                colorClass="text-cyan-400"
                            />
                        )}
                        <ChevronDown
                            size={16}
                            className={`text-outline expandable-chevron ${showPatternPack ? 'rotate-180' : ''}`}
                        />
                    </div>
                </button>

                <div
                    className={`expandable-panel ${
                        showPatternPack ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                    }`}
                >
                    <div className="overflow-hidden">
                        <div className="p-6 space-y-5">
                            {patternPackError && (
                                <div className="text-xs text-rose-300">
                                    Unable to load pattern pack. Please retry later.
                                </div>
                            )}

                            {!patternPackData && !patternPackError && (
                                <div className="text-xs text-outline">
                                    Pattern pack data will appear here once loaded.
                                </div>
                            )}

                            {patternPackData && patternPackSummary && (
                                <>
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-1">Timeframes</div>
                                            <div className="text-lg font-black text-on-surface">{patternPackSummary.summaries.length}</div>
                                        </div>
                                        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-1">Levels</div>
                                            <div className="text-lg font-black text-on-surface">{patternPackSummary.totalLevels}</div>
                                        </div>
                                        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-1">Flags</div>
                                            <div className="text-lg font-black text-on-surface">{patternPackSummary.totalFlags}</div>
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
                                            <div key={frame.timeframe} className="bg-surface-container-low p-5 rounded-xl border border-outline-variant/20 space-y-4">
                                                <div className="flex items-center justify-between">
                                                    <div className="text-xs font-black uppercase tracking-[0.2em] text-on-surface-variant">
                                                        {formatLabel(frame.timeframe)}
                                                    </div>
                                                    <div className="text-[10px] text-outline font-bold uppercase">
                                                        Supports {frame.supportCount} · Resist {frame.resistanceCount} · Flags {frame.flagCount}
                                                    </div>
                                                </div>

                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                    <div>
                                                        <div className="text-[9px] font-bold text-outline uppercase mb-2">Support Levels</div>
                                                        {frame.supportLevels.length > 0 ? (
                                                            <div className="space-y-2">
                                                                {frame.supportLevels.map((level, idx) => (
                                                                    <div key={`${frame.timeframe}-support-${idx}`} className="flex items-center justify-between text-xs text-on-surface">
                                                                        <span>{level.label ? formatLabel(level.label) : 'Support'} @ {formatPrice(level.price)}</span>
                                                                        <span className="text-[10px] text-outline">
                                                                            {level.strength !== null && level.strength !== undefined ? `Strength ${level.strength.toFixed(2)}` : 'Strength n/a'}
                                                                        </span>
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        ) : (
                                                            <div className="text-xs text-outline">No Support Levels Detected</div>
                                                        )}
                                                    </div>
                                                    <div>
                                                        <div className="text-[9px] font-bold text-outline uppercase mb-2">Resistance Levels</div>
                                                        {frame.resistanceLevels.length > 0 ? (
                                                            <div className="space-y-2">
                                                                {frame.resistanceLevels.map((level, idx) => (
                                                                    <div key={`${frame.timeframe}-resistance-${idx}`} className="flex items-center justify-between text-xs text-on-surface">
                                                                        <span>{level.label ? formatLabel(level.label) : 'Resistance'} @ {formatPrice(level.price)}</span>
                                                                        <span className="text-[10px] text-outline">
                                                                            {level.strength !== null && level.strength !== undefined ? `Strength ${level.strength.toFixed(2)}` : 'Strength n/a'}
                                                                        </span>
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        ) : (
                                                            <div className="text-xs text-outline">No Resistance Levels Detected</div>
                                                        )}
                                                    </div>
                                                </div>

                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                    <div>
                                                        <div className="text-[9px] font-bold text-outline uppercase mb-2">Breakouts</div>
                                                        {frame.breakoutFlags.length > 0 ? (
                                                            <div className="flex flex-wrap gap-2">
                                                                {frame.breakoutFlags.map((flag, idx) => (
                                                                    <span key={`${frame.timeframe}-breakout-${idx}`} className="px-2.5 py-1 bg-surface-container border border-outline-variant/20 rounded-full text-[10px] font-bold text-on-surface uppercase tracking-wide">
                                                                        {flag.name} {flag.confidence !== null && flag.confidence !== undefined ? `(${flag.confidence.toFixed(2)})` : ''}
                                                                    </span>
                                                                ))}
                                                            </div>
                                                        ) : (
                                                            <div className="text-xs text-outline">No Breakout Flags Detected</div>
                                                        )}
                                                    </div>
                                                    <div>
                                                        <div className="text-[9px] font-bold text-outline uppercase mb-2">Trendlines</div>
                                                        {frame.trendFlags.length > 0 ? (
                                                            <div className="flex flex-wrap gap-2">
                                                                {frame.trendFlags.map((flag, idx) => (
                                                                    <span key={`${frame.timeframe}-trend-${idx}`} className="px-2.5 py-1 bg-surface-container border border-outline-variant/20 rounded-full text-[10px] font-bold text-on-surface uppercase tracking-wide">
                                                                        {flag.name} {flag.confidence !== null && flag.confidence !== undefined ? `(${flag.confidence.toFixed(2)})` : ''}
                                                                    </span>
                                                                ))}
                                                            </div>
                                                        ) : (
                                                            <div className="text-xs text-outline">No Trendline Flags Detected</div>
                                                        )}
                                                    </div>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                </div>
            </section>
        )}

        {fusionReportId && (
            <section className="rounded-xl border border-outline-variant/10 bg-surface-container overflow-hidden transition-colors duration-300">
                <button
                    onClick={() => setShowFusionReport(!showFusionReport)}
                    className="w-full flex items-center justify-between p-4 bg-surface-container-low hover:bg-surface-container-low transition-colors"
                >
                    <div className="flex items-center gap-2">
                        <Layers size={14} className="text-outline" />
                        <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">Fusion Report</span>
                    </div>
                    <div className="flex items-center gap-4">
                        {showFusionReport &&
                            (isFusionReportLoading || isDirectionScorecardLoading) && (
                                <AgentLoadingState
                                    type="header"
                                    title="Loading Fusion Report…"
                                    colorClass="text-cyan-400"
                                />
                            )}
                        <ChevronDown
                            size={16}
                            className={`text-outline expandable-chevron ${showFusionReport ? 'rotate-180' : ''}`}
                        />
                    </div>
                </button>

                <div
                    className={`expandable-panel ${
                        showFusionReport ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                    }`}
                >
                    <div className="overflow-hidden">
                        <div className="p-6 space-y-5">
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
                                <div className="text-xs text-outline">
                                    Fusion report data will appear here once loaded.
                                </div>
                            )}

                            {fusionReportData && (
                                <>
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-1">Timeframes</div>
                                            <div className="text-lg font-black text-on-surface">{fusionReportSummary?.totalFrames ?? 0}</div>
                                        </div>
                                        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-1">Conflicts</div>
                                            <div className="text-lg font-black text-on-surface">{fusionReportData.conflict_reasons?.length ?? 0}</div>
                                        </div>
                                        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-1">Signal Strength</div>
                                            <div className="text-lg font-black text-on-surface">
                                                {fusionReportData.signal_strength_effective !== undefined &&
                                                    fusionReportData.signal_strength_effective !== null
                                                    ? formatConfidence(fusionReportData.signal_strength_effective)
                                                    : fusionConfidenceDisplay}
                                            </div>
                                            <div className="text-[9px] text-outline uppercase tracking-[0.2em] mt-1">{fusionConfidenceLabel}</div>
                                            {fusionReportData.confidence_eligibility?.eligible === false && (
                                                <div className="text-[9px] text-outline uppercase tracking-[0.2em] mt-1">
                                                    Not Probability-Rated
                                                </div>
                                            )}
                                            {fusionRawDisplay && (
                                                <div className="text-[9px] text-outline uppercase tracking-[0.2em] mt-1">
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
                                                <div key={entry.timeframe} className="bg-surface-container-low p-5 rounded-xl border border-outline-variant/20 space-y-3">
                                                    <div className="flex items-center justify-between">
                                                        <div className="text-xs font-black uppercase tracking-[0.2em] text-on-surface-variant">
                                                            {formatLabel(entry.timeframe)}
                                                        </div>
                                                        <div className="text-[10px] text-outline font-bold uppercase">
                                                            Classic · Quant · Pattern
                                                        </div>
                                                    </div>
                                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                                        <div className="bg-surface-container-low p-3 rounded-lg border border-outline-variant/20">
                                                            <div className="text-[9px] text-outline font-bold uppercase mb-1">Classic</div>
                                                            <div className="text-sm font-black text-on-surface">{formatLabel(entry.classic)}</div>
                                                            <div className="text-[10px] text-outline">Score {entry.classicScore !== null ? entry.classicScore.toFixed(2) : 'n/a'}</div>
                                                        </div>
                                                        <div className="bg-surface-container-low p-3 rounded-lg border border-outline-variant/20">
                                                            <div className="text-[9px] text-outline font-bold uppercase mb-1">Quant</div>
                                                            <div className="text-sm font-black text-on-surface">{formatLabel(entry.quant)}</div>
                                                            <div className="text-[10px] text-outline">Score {entry.quantScore !== null ? entry.quantScore.toFixed(2) : 'n/a'}</div>
                                                        </div>
                                                        <div className="bg-surface-container-low p-3 rounded-lg border border-outline-variant/20">
                                                            <div className="text-[9px] text-outline font-bold uppercase mb-1">Pattern</div>
                                                            <div className="text-sm font-black text-on-surface">{formatLabel(entry.pattern)}</div>
                                                            <div className="text-[10px] text-outline">Score {entry.patternScore !== null ? entry.patternScore.toFixed(2) : 'n/a'}</div>
                                                        </div>
                                                    </div>
                                                </div>
                                        ))}
                                    </div>
                                )}

                                {directionScorecardData && scorecardSummary && scorecardSummary.entries.length > 0 && (
                                    <div className="space-y-4">
                                        <div className="flex items-center justify-between">
                                            <div className="text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant">
                                                Direction Scorecard
                                            </div>
                                            <div className="text-[10px] text-outline font-bold uppercase">
                                                Model {scorecardSummary.modelVersion ?? 'n/a'} · Neutral {scorecardSummary.neutralThreshold.toFixed(2)}
                                            </div>
                                        </div>
                                        <div className="grid grid-cols-1 gap-4">
                                            {scorecardSummary.entries.map(({ timeframe, frame }) => (
                                                <div key={timeframe} className="bg-surface-container-low p-5 rounded-xl border border-outline-variant/20 space-y-4">
                                                    <div className="flex items-center justify-between">
                                                        <div className="text-xs font-black uppercase tracking-[0.2em] text-on-surface-variant">
                                                            {formatLabel(timeframe)}
                                                        </div>
                                                        <div className="text-[10px] text-outline font-bold uppercase">
                                                            Total {formatContributionValue(frame.total_score)}
                                                        </div>
                                                    </div>
                                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                                        <div className="bg-surface-container-low p-3 rounded-lg border border-outline-variant/20 space-y-2">
                                                            <div className="text-[9px] text-outline font-bold uppercase">Classic</div>
                                                            <div className="text-sm font-black text-on-surface">{formatLabel(frame.classic_label)}</div>
                                                            <div className="text-[10px] text-outline">Score {frame.classic_score.toFixed(2)}</div>
                                                            {renderScorecardContributions(frame.contributions?.classic ?? [])}
                                                        </div>
                                                        <div className="bg-surface-container-low p-3 rounded-lg border border-outline-variant/20 space-y-2">
                                                            <div className="text-[9px] text-outline font-bold uppercase">Quant</div>
                                                            <div className="text-sm font-black text-on-surface">{formatLabel(frame.quant_label)}</div>
                                                            <div className="text-[10px] text-outline">Score {frame.quant_score.toFixed(2)}</div>
                                                            {renderScorecardContributions(frame.contributions?.quant ?? [])}
                                                        </div>
                                                        <div className="bg-surface-container-low p-3 rounded-lg border border-outline-variant/20 space-y-2">
                                                            <div className="text-[9px] text-outline font-bold uppercase">Pattern</div>
                                                            <div className="text-sm font-black text-on-surface">{formatLabel(frame.pattern_label)}</div>
                                                            <div className="text-[10px] text-outline">Score {frame.pattern_score.toFixed(2)}</div>
                                                            {renderScorecardContributions(frame.contributions?.pattern ?? [])}
                                                        </div>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {fusionReportData.alignment_report && Object.keys(fusionReportData.alignment_report).length > 0 && (
                                    <div className="text-xs text-on-surface-variant">
                                        Alignment report attached ({Object.keys(fusionReportData.alignment_report).length} fields).
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                </div>
            </div>
            </section>
        )}

        {verificationReportId && (
            <section className="rounded-xl border border-outline-variant/10 bg-surface-container overflow-hidden transition-colors duration-300">
                <button
                    onClick={() =>
                        setShowVerificationReport(!showVerificationReport)
                    }
                    className="w-full flex items-center justify-between p-4 bg-surface-container-low hover:bg-surface-container-low transition-colors"
                >
                    <div className="flex items-center gap-2">
                        <Layers size={14} className="text-outline" />
                        <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">Verification &amp; Baseline</span>
                    </div>
                    <div className="flex items-center gap-4">
                        {showVerificationReport && isVerificationReportLoading && (
                            <AgentLoadingState
                                type="header"
                                title="Loading Verification Report…"
                                colorClass="text-cyan-400"
                            />
                        )}
                        <ChevronDown
                            size={16}
                            className={`text-outline expandable-chevron ${showVerificationReport ? 'rotate-180' : ''}`}
                        />
                    </div>
                </button>

                <div
                    className={`expandable-panel ${
                        showVerificationReport ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                    }`}
                >
                    <div className="overflow-hidden">
                        <div className="p-6 space-y-5">
                            {verificationReportError && (
                                <div className="text-xs text-rose-300">
                                    Unable to load verification report. Please retry later.
                                </div>
                            )}

                            {!verificationReportData && !verificationReportError && (
                                <div className="text-xs text-outline">
                                    Verification report data will appear here once loaded.
                                </div>
                            )}

                            {verificationReportData && (
                                <>
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-1">Baseline Gates</div>
                                            <div className="text-lg font-black text-on-surface">{verificationSummary?.gatesCount ?? 0}</div>
                                        </div>
                                        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-1">Robustness Flags</div>
                                            <div className="text-lg font-black text-on-surface">{verificationSummary?.flagsCount ?? 0}</div>
                                        </div>
                                        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-1">As Of</div>
                                            <div className="text-lg font-black text-on-surface">{verificationReportData.as_of}</div>
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
                                        <div className="bg-surface-container-low p-5 rounded-xl border border-outline-variant/20 space-y-3">
                                            <div className="text-[9px] font-bold text-outline uppercase">Backtest Summary</div>
                                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-on-surface">
                                                <div>Win Rate: {verificationReportData.backtest_summary.win_rate ?? 'n/a'}</div>
                                                <div>Profit Factor: {verificationReportData.backtest_summary.profit_factor ?? 'n/a'}</div>
                                                <div>Sharpe: {verificationReportData.backtest_summary.sharpe_ratio ?? 'n/a'}</div>
                                                <div>Max DD: {verificationReportData.backtest_summary.max_drawdown ?? 'n/a'}</div>
                                                <div>Total Trades: {verificationReportData.backtest_summary.total_trades ?? 'n/a'}</div>
                                            </div>
                                        </div>
                                    )}

                                    {verificationReportData.wfa_summary && (
                                        <div className="bg-surface-container-low p-5 rounded-xl border border-outline-variant/20 space-y-3">
                                            <div className="text-[9px] font-bold text-outline uppercase">Walk-Forward Summary</div>
                                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-on-surface">
                                                <div>WFA Sharpe: {verificationReportData.wfa_summary.wfa_sharpe ?? 'n/a'}</div>
                                                <div>WFE Ratio: {verificationReportData.wfa_summary.wfe_ratio ?? 'n/a'}</div>
                                                <div>Max DD: {verificationReportData.wfa_summary.wfa_max_drawdown ?? 'n/a'}</div>
                                                <div>Periods: {verificationReportData.wfa_summary.period_count ?? 'n/a'}</div>
                                            </div>
                                        </div>
                                    )}

                                    {verificationReportData.baseline_gates && Object.keys(verificationReportData.baseline_gates).length > 0 && (
                                        <div className="bg-surface-container-low p-5 rounded-xl border border-outline-variant/20">
                                            <div className="text-[9px] font-bold text-outline uppercase mb-3">Baseline Gates</div>
                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs text-on-surface">
                                                {Object.entries(verificationReportData.baseline_gates).map(([key, value]) => (
                                                    <div key={key} className="flex items-center justify-between bg-surface-container border border-outline-variant/20 rounded-lg px-3 py-2">
                                                        <span className="font-bold uppercase text-[9px] text-outline">{formatLabel(key)}</span>
                                                        <span>{typeof value === 'boolean' ? (value ? 'PASS' : 'FAIL') : String(value)}</span>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    </div>
                </div>
            </section>
        )}

        <section className="rounded-xl border border-outline-variant/10 bg-surface-container p-6">
            <div className="flex items-center gap-2 mb-6">
                <Layers size={16} className="text-purple-400" />
                <span className="text-xs font-bold text-outline uppercase tracking-[0.2em]">Artifact References</span>
            </div>
            {artifactEntries.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {artifactEntries.map(([key, value]) => (
                        <div key={key} className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/20">
                            <div className="text-[9px] font-bold text-outline uppercase mb-1">
                                {formatArtifactLabel(key)} ID
                            </div>
                            <div className="text-sm font-mono font-bold text-on-surface">{formatArtifactId(value)}</div>
                        </div>
                    ))}
                </div>
            ) : (
                <div className="text-xs text-outline">No Linked Artifacts Available</div>
            )}
        </section>
    </section>
);
