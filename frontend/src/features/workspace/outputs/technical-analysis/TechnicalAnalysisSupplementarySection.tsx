import React from 'react';
import { Bell, ChevronDown, Layers } from 'lucide-react';
import type { ArtifactRetryContract } from '../../../../hooks/useArtifact';
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
import { ArtifactLoadError } from '../shared/ArtifactLoadError';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';

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

const ArtifactLoadStatus: React.FC<{ label: string; isLoading: boolean }> = ({ label, isLoading }) => (
    isLoading ? (
        <AgentLoadingState type="block" title={`Loading ${label.toLowerCase()}…`} />
    ) : (
        <EmptyState
            className="bg-muted/20 px-4 py-6"
            title={`${label} unavailable`}
            description={`No ${label.toLowerCase()} data was returned for this run.`}
        />
    )
);

export interface TechnicalAnalysisSupplementarySectionProps {
    alertsId: string | null;
    alertsData?: TechnicalAlertsArtifact | null;
    alertsSummary: AlertsSummary | null;
    alertsError?: Error | null;
    alertsRetry: ArtifactRetryContract;
    isAlertsLoadingState: boolean;
    showAlerts: boolean;
    setShowAlerts: React.Dispatch<React.SetStateAction<boolean>>;
    featurePackId: string | null;
    featurePackData?: TechnicalFeaturePack | null;
    featurePackSummary: FeaturePackSummary | null;
    featurePackError?: Error | null;
    featurePackRetry: ArtifactRetryContract;
    isFeaturePackLoading: boolean;
    showFeaturePack: boolean;
    setShowFeaturePack: React.Dispatch<React.SetStateAction<boolean>>;
    patternPackId: string | null;
    patternPackData?: TechnicalPatternPack | null;
    patternPackSummary: PatternPackSummary | null;
    patternPackError?: Error | null;
    patternPackRetry: ArtifactRetryContract;
    isPatternPackLoading: boolean;
    showPatternPack: boolean;
    setShowPatternPack: React.Dispatch<React.SetStateAction<boolean>>;
    fusionReportId: string | null;
    fusionReportData?: TechnicalFusionReport | null;
    fusionReportSummary: FusionReportSummary | null;
    fusionReportError?: Error | null;
    fusionReportRetry: ArtifactRetryContract;
    isFusionReportLoading: boolean;
    fusionConfidenceDisplay: string;
    fusionConfidenceLabel: string;
    fusionRawDisplay: string | null;
    showFusionReport: boolean;
    setShowFusionReport: React.Dispatch<React.SetStateAction<boolean>>;
    directionScorecardData?: TechnicalDirectionScorecard | null;
    scorecardSummary: ScorecardSummary | null;
    directionScorecardError?: Error | null;
    directionScorecardRetry: ArtifactRetryContract;
    isDirectionScorecardLoading: boolean;
    verificationReportId: string | null;
    verificationReportData?: TechnicalVerificationReport | null;
    verificationSummary: VerificationSummary | null;
    verificationReportError?: Error | null;
    verificationReportRetry: ArtifactRetryContract;
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
    alertsRetry,
    isAlertsLoadingState,
    showAlerts,
    setShowAlerts,
    featurePackId,
    featurePackData,
    featurePackSummary,
    featurePackError,
    featurePackRetry,
    isFeaturePackLoading,
    showFeaturePack,
    setShowFeaturePack,
    patternPackId,
    patternPackData,
    patternPackSummary,
    patternPackError,
    patternPackRetry,
    isPatternPackLoading,
    showPatternPack,
    setShowPatternPack,
    fusionReportId,
    fusionReportData,
    fusionReportSummary,
    fusionReportError,
    fusionReportRetry,
    isFusionReportLoading,
    fusionConfidenceDisplay,
    fusionConfidenceLabel,
    fusionRawDisplay,
    showFusionReport,
    setShowFusionReport,
    directionScorecardData,
    scorecardSummary,
    directionScorecardError,
    directionScorecardRetry,
    isDirectionScorecardLoading,
    verificationReportId,
    verificationReportData,
    verificationSummary,
    verificationReportError,
    verificationReportRetry,
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
            <Layers size={14} className="text-primary opacity-70" />
            <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">Other</span>
        </div>

        {alertsId && (
            <Card className="overflow-hidden border border-border/30 p-0">
                <Button
                    type="button"
                    variant="ghost"
                    aria-expanded={showAlerts}
                    onClick={() => setShowAlerts(!showAlerts)}
                    className="h-auto w-full justify-between whitespace-normal rounded-none bg-muted/30 p-4 text-left hover:bg-muted/50"
                >
                    <div className="flex items-center gap-2">
                        <Bell size={14} className="text-muted-foreground" />
                        <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">Alert Signals</span>
                    </div>
                    <div className="flex items-center gap-4">
                        {showAlerts && isAlertsLoadingState && (
                            <AgentLoadingState
                                type="header"
                                title="Loading Alerts…"

                            />
                        )}
                        {alertsSummary && (
                            <div className="flex items-center gap-2 text-[9px] font-bold uppercase text-muted-foreground">
                                <span>Total {alertsSummary.total}</span>
                                <span className="text-destructive">C {alertsSummary.severityCounts.critical}</span>
                                <span className="text-warning">W {alertsSummary.severityCounts.warning}</span>
                                <span className="text-muted-foreground">I {alertsSummary.severityCounts.info}</span>
                            </div>
                        )}
                        <ChevronDown
                            size={16}
                            className={`text-muted-foreground expandable-chevron ${showAlerts ? 'rotate-180' : ''}`}
                        />
                    </div>
                </Button>

                <div
                    className={`expandable-panel ${
                        showAlerts ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                    }`}
                >
                    <div className="overflow-hidden">
                        <div className="p-6 space-y-5">
                            {alertsError && (
                                <ArtifactLoadError title="Alerts unavailable" error={alertsError} {...alertsRetry} />
                            )}

                            {!alertsData && !alertsError && (
                                <ArtifactLoadStatus label="Alerts" isLoading={isAlertsLoadingState} />
                            )}

                            {alertsData && alertsSummary && (
                                <>
                                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                                        <div className="bg-muted/50 p-4 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">Total Alerts</div>
                                            <div className="text-lg font-black text-foreground">{alertsSummary.total}</div>
                                        </div>
                                        <div className="bg-muted/50 p-4 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">Critical</div>
                                            <div className="text-lg font-black text-destructive">{alertsSummary.severityCounts.critical}</div>
                                        </div>
                                        <div className="bg-muted/50 p-4 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">Warning</div>
                                            <div className="text-lg font-black text-warning">{alertsSummary.severityCounts.warning}</div>
                                        </div>
                                        <div className="bg-muted/50 p-4 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">Info</div>
                                            <div className="text-lg font-black text-foreground">{alertsSummary.severityCounts.info}</div>
                                        </div>
                                    </div>

                                    {alertsSummary.generatedAt && (
                                        <div className="text-[10px] text-muted-foreground">
                                            Generated at {alertsSummary.generatedAt}
                                        </div>
                                    )}

                                    {alertsData.degraded_reasons && alertsData.degraded_reasons.length > 0 && (
                                        <div className="flex flex-wrap gap-2">
                                            {alertsData.degraded_reasons.map((reason) => (
                                                <span key={reason} className="px-3 py-1 bg-destructive/10 border border-destructive/20 rounded-full text-[10px] font-bold text-destructive uppercase tracking-wider">
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
                                                        className="bg-muted/50 p-4 rounded-lg border border-border/20 space-y-3"
                                                    >
                                                        <div className="flex items-start justify-between gap-4">
                                                            <div>
                                                                <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-muted-foreground mb-1">
                                                                    {alert.timeframe.toUpperCase()} · {formatLabel(alert.code)}
                                                                </div>
                                                                <div className="text-sm font-black text-foreground">{alert.title}</div>
                                                                {alert.message && (
                                                                    <div className="text-xs text-muted-foreground mt-1">
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
                                                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-[10px] text-muted-foreground">
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
                                        <div className="text-xs text-muted-foreground">
                                            No Alert Signals Detected For The Current Window
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    </div>
                </div>
            </Card>
        )}

        {featurePackId && (
            <Card className="overflow-hidden border border-border/30 p-0">
                <Button
                    type="button"
                    variant="ghost"
                    aria-expanded={showFeaturePack}
                    onClick={() => setShowFeaturePack(!showFeaturePack)}
                    className="h-auto w-full justify-between whitespace-normal rounded-none bg-muted/30 p-4 text-left hover:bg-muted/50"
                >
                    <div className="flex items-center gap-2">
                        <Layers size={14} className="text-muted-foreground" />
                        <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">Feature Pack</span>
                    </div>
                    <div className="flex items-center gap-4">
                        {showFeaturePack && isFeaturePackLoading && (
                            <AgentLoadingState
                                type="header"
                                title="Loading Feature Pack…"

                            />
                        )}
                        <ChevronDown
                            size={16}
                            className={`text-muted-foreground expandable-chevron ${showFeaturePack ? 'rotate-180' : ''}`}
                        />
                    </div>
                </Button>

                <div
                    className={`expandable-panel ${
                        showFeaturePack ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                    }`}
                >
                    <div className="overflow-hidden">
                        <div className="p-6 space-y-5">
                            {featurePackError && (
                                <ArtifactLoadError title="Feature pack unavailable" error={featurePackError} {...featurePackRetry} />
                            )}

                            {!featurePackData && !featurePackError && (
                                <ArtifactLoadStatus label="Feature pack" isLoading={isFeaturePackLoading} />
                            )}

                            {featurePackData && featurePackSummary && (
                                <>
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                        <div className="bg-muted/50 p-4 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">Timeframes</div>
                                            <div className="text-lg font-black text-foreground">{featurePackSummary.summaries.length}</div>
                                        </div>
                                        <div className="bg-muted/50 p-4 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">Classic Indicators</div>
                                            <div className="text-lg font-black text-foreground">{featurePackSummary.classicTotal}</div>
                                        </div>
                                        <div className="bg-muted/50 p-4 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">Quant Features</div>
                                            <div className="text-lg font-black text-foreground">{featurePackSummary.quantTotal}</div>
                                        </div>
                                    </div>

                                    {featurePackData.degraded_reasons && featurePackData.degraded_reasons.length > 0 && (
                                        <div className="flex flex-wrap gap-2">
                                            {featurePackData.degraded_reasons.map((reason) => (
                                                <span key={reason} className="px-3 py-1 bg-destructive/10 border border-destructive/20 rounded-full text-[10px] font-bold text-destructive uppercase tracking-wider">
                                                    {reason.replace('_', ' ')}
                                                </span>
                                            ))}
                                        </div>
                                    )}

                                    <div className="grid grid-cols-1 gap-4">
                                        {featurePackSummary.summaries.map((frame) => (
                                            <div key={frame.timeframe} className="bg-muted/50 p-5 rounded-lg border border-border/20 space-y-3">
                                                <div className="flex items-center justify-between">
                                                    <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                                                        {formatLabel(frame.timeframe)}
                                                    </div>
                                                    <div className="text-[10px] text-muted-foreground font-bold uppercase">
                                                        Classic {frame.classicCount} · Quant {frame.quantCount}
                                                    </div>
                                                </div>
                                                <div>
                                                    <div className="text-[9px] font-bold text-muted-foreground uppercase mb-2">Classic Highlights</div>
                                                    {renderIndicatorHighlights(frame.classicHighlights)}
                                                </div>
                                                <div>
                                                    <div className="text-[9px] font-bold text-muted-foreground uppercase mb-2">Quant Highlights</div>
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
            </Card>
        )}

        {patternPackId && (
            <Card className="overflow-hidden border border-border/30 p-0">
                <Button
                    type="button"
                    variant="ghost"
                    aria-expanded={showPatternPack}
                    onClick={() => setShowPatternPack(!showPatternPack)}
                    className="h-auto w-full justify-between whitespace-normal rounded-none bg-muted/30 p-4 text-left hover:bg-muted/50"
                >
                    <div className="flex items-center gap-2">
                        <Layers size={14} className="text-muted-foreground" />
                        <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">Pattern Pack</span>
                    </div>
                    <div className="flex items-center gap-4">
                        {showPatternPack && isPatternPackLoading && (
                            <AgentLoadingState
                                type="header"
                                title="Loading Pattern Pack…"

                            />
                        )}
                        <ChevronDown
                            size={16}
                            className={`text-muted-foreground expandable-chevron ${showPatternPack ? 'rotate-180' : ''}`}
                        />
                    </div>
                </Button>

                <div
                    className={`expandable-panel ${
                        showPatternPack ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                    }`}
                >
                    <div className="overflow-hidden">
                        <div className="p-6 space-y-5">
                            {patternPackError && (
                                <ArtifactLoadError title="Pattern pack unavailable" error={patternPackError} {...patternPackRetry} />
                            )}

                            {!patternPackData && !patternPackError && (
                                <ArtifactLoadStatus label="Pattern pack" isLoading={isPatternPackLoading} />
                            )}

                            {patternPackData && patternPackSummary && (
                                <>
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                        <div className="bg-muted/50 p-4 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">Timeframes</div>
                                            <div className="text-lg font-black text-foreground">{patternPackSummary.summaries.length}</div>
                                        </div>
                                        <div className="bg-muted/50 p-4 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">Levels</div>
                                            <div className="text-lg font-black text-foreground">{patternPackSummary.totalLevels}</div>
                                        </div>
                                        <div className="bg-muted/50 p-4 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">Flags</div>
                                            <div className="text-lg font-black text-foreground">{patternPackSummary.totalFlags}</div>
                                        </div>
                                    </div>

                                    {patternPackData.degraded_reasons && patternPackData.degraded_reasons.length > 0 && (
                                        <div className="flex flex-wrap gap-2">
                                            {patternPackData.degraded_reasons.map((reason) => (
                                                <span key={reason} className="px-3 py-1 bg-destructive/10 border border-destructive/20 rounded-full text-[10px] font-bold text-destructive uppercase tracking-wider">
                                                    {reason.replace('_', ' ')}
                                                </span>
                                            ))}
                                        </div>
                                    )}

                                    <div className="grid grid-cols-1 gap-4">
                                        {patternPackSummary.summaries.map((frame) => (
                                            <div key={frame.timeframe} className="bg-muted/50 p-5 rounded-lg border border-border/20 space-y-4">
                                                <div className="flex items-center justify-between">
                                                    <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                                                        {formatLabel(frame.timeframe)}
                                                    </div>
                                                    <div className="text-[10px] text-muted-foreground font-bold uppercase">
                                                        Supports {frame.supportCount} · Resist {frame.resistanceCount} · Flags {frame.flagCount}
                                                    </div>
                                                </div>

                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                    <div>
                                                        <div className="text-[9px] font-bold text-muted-foreground uppercase mb-2">Support Levels</div>
                                                        {frame.supportLevels.length > 0 ? (
                                                            <div className="space-y-2">
                                                                {frame.supportLevels.map((level, idx) => (
                                                                    <div key={`${frame.timeframe}-support-${idx}`} className="flex items-center justify-between text-xs text-foreground">
                                                                        <span>{level.label ? formatLabel(level.label) : 'Support'} @ {formatPrice(level.price)}</span>
                                                                        <span className="text-[10px] text-muted-foreground">
                                                                            {level.strength !== null && level.strength !== undefined ? `Strength ${level.strength.toFixed(2)}` : 'Strength n/a'}
                                                                        </span>
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        ) : (
                                                            <div className="text-xs text-muted-foreground">No Support Levels Detected</div>
                                                        )}
                                                    </div>
                                                    <div>
                                                        <div className="text-[9px] font-bold text-muted-foreground uppercase mb-2">Resistance Levels</div>
                                                        {frame.resistanceLevels.length > 0 ? (
                                                            <div className="space-y-2">
                                                                {frame.resistanceLevels.map((level, idx) => (
                                                                    <div key={`${frame.timeframe}-resistance-${idx}`} className="flex items-center justify-between text-xs text-foreground">
                                                                        <span>{level.label ? formatLabel(level.label) : 'Resistance'} @ {formatPrice(level.price)}</span>
                                                                        <span className="text-[10px] text-muted-foreground">
                                                                            {level.strength !== null && level.strength !== undefined ? `Strength ${level.strength.toFixed(2)}` : 'Strength n/a'}
                                                                        </span>
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        ) : (
                                                            <div className="text-xs text-muted-foreground">No Resistance Levels Detected</div>
                                                        )}
                                                    </div>
                                                </div>

                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                    <div>
                                                        <div className="text-[9px] font-bold text-muted-foreground uppercase mb-2">Breakouts</div>
                                                        {frame.breakoutFlags.length > 0 ? (
                                                            <div className="flex flex-wrap gap-2">
                                                                {frame.breakoutFlags.map((flag, idx) => (
                                                                    <span key={`${frame.timeframe}-breakout-${idx}`} className="px-2.5 py-1 bg-card border border-border/20 rounded-full text-[10px] font-bold text-foreground uppercase tracking-wide">
                                                                        {flag.name} {flag.confidence !== null && flag.confidence !== undefined ? `(${flag.confidence.toFixed(2)})` : ''}
                                                                    </span>
                                                                ))}
                                                            </div>
                                                        ) : (
                                                            <div className="text-xs text-muted-foreground">No Breakout Flags Detected</div>
                                                        )}
                                                    </div>
                                                    <div>
                                                        <div className="text-[9px] font-bold text-muted-foreground uppercase mb-2">Trendlines</div>
                                                        {frame.trendFlags.length > 0 ? (
                                                            <div className="flex flex-wrap gap-2">
                                                                {frame.trendFlags.map((flag, idx) => (
                                                                    <span key={`${frame.timeframe}-trend-${idx}`} className="px-2.5 py-1 bg-card border border-border/20 rounded-full text-[10px] font-bold text-foreground uppercase tracking-wide">
                                                                        {flag.name} {flag.confidence !== null && flag.confidence !== undefined ? `(${flag.confidence.toFixed(2)})` : ''}
                                                                    </span>
                                                                ))}
                                                            </div>
                                                        ) : (
                                                            <div className="text-xs text-muted-foreground">No Trendline Flags Detected</div>
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
            </Card>
        )}

        {fusionReportId && (
            <Card className="overflow-hidden border border-border/30 p-0">
                <Button
                    type="button"
                    variant="ghost"
                    aria-expanded={showFusionReport}
                    onClick={() => setShowFusionReport(!showFusionReport)}
                    className="h-auto w-full justify-between whitespace-normal rounded-none bg-muted/30 p-4 text-left hover:bg-muted/50"
                >
                    <div className="flex items-center gap-2">
                        <Layers size={14} className="text-muted-foreground" />
                        <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">Fusion Report</span>
                    </div>
                    <div className="flex items-center gap-4">
                        {showFusionReport &&
                            (isFusionReportLoading || isDirectionScorecardLoading) && (
                                <AgentLoadingState
                                    type="header"
                                    title="Loading Fusion Report…"

                                />
                            )}
                        <ChevronDown
                            size={16}
                            className={`text-muted-foreground expandable-chevron ${showFusionReport ? 'rotate-180' : ''}`}
                        />
                    </div>
                </Button>

                <div
                    className={`expandable-panel ${
                        showFusionReport ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                    }`}
                >
                    <div className="overflow-hidden">
                        <div className="p-6 space-y-5">
                            {fusionReportError && (
                                <ArtifactLoadError title="Fusion report unavailable" error={fusionReportError} {...fusionReportRetry} />
                            )}

                            {directionScorecardError && (
                                <ArtifactLoadError title="Direction scorecard unavailable" error={directionScorecardError} {...directionScorecardRetry} />
                            )}

                            {!fusionReportData && !fusionReportError && (
                                <ArtifactLoadStatus
                                    label="Fusion report"
                                    isLoading={isFusionReportLoading || isDirectionScorecardLoading}
                                />
                            )}

                            {fusionReportData && (
                                <>
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                        <div className="bg-muted/50 p-4 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">Timeframes</div>
                                            <div className="text-lg font-black text-foreground">{fusionReportSummary?.totalFrames ?? 0}</div>
                                        </div>
                                        <div className="bg-muted/50 p-4 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">Conflicts</div>
                                            <div className="text-lg font-black text-foreground">{fusionReportData.conflict_reasons?.length ?? 0}</div>
                                        </div>
                                        <div className="bg-muted/50 p-4 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">Signal Strength</div>
                                            <div className="text-lg font-black text-foreground">
                                                {fusionReportData.signal_strength_effective !== undefined &&
                                                    fusionReportData.signal_strength_effective !== null
                                                    ? formatConfidence(fusionReportData.signal_strength_effective)
                                                    : fusionConfidenceDisplay}
                                            </div>
                                            <div className="text-[9px] text-muted-foreground uppercase tracking-[0.2em] mt-1">{fusionConfidenceLabel}</div>
                                            {fusionReportData.confidence_eligibility?.eligible === false && (
                                                <div className="text-[9px] text-muted-foreground uppercase tracking-[0.2em] mt-1">
                                                    Not Probability-Rated
                                                </div>
                                            )}
                                            {fusionRawDisplay && (
                                                <div className="text-[9px] text-muted-foreground uppercase tracking-[0.2em] mt-1">
                                                    Raw {fusionRawDisplay}
                                                </div>
                                            )}
                                        </div>
                                    </div>

                                    {fusionReportData.degraded_reasons && fusionReportData.degraded_reasons.length > 0 && (
                                        <div className="flex flex-wrap gap-2">
                                            {fusionReportData.degraded_reasons.map((reason) => (
                                                <span key={reason} className="px-3 py-1 bg-destructive/10 border border-destructive/20 rounded-full text-[10px] font-bold text-destructive uppercase tracking-wider">
                                                    {reason.replace('_', ' ')}
                                                </span>
                                            ))}
                                        </div>
                                    )}

                                    {fusionReportData.conflict_reasons && fusionReportData.conflict_reasons.length > 0 && (
                                        <div className="flex flex-wrap gap-2">
                                            {fusionReportData.conflict_reasons.map((reason) => (
                                                <span key={reason} className="px-3 py-1 bg-warning/10 border border-warning/20 rounded-full text-[10px] font-bold text-warning uppercase tracking-wider">
                                                    {reason.replace('_', ' ')}
                                                </span>
                                            ))}
                                        </div>
                                    )}

                                    {fusionReportSummary && fusionReportSummary.entries.length > 0 && (
                                        <div className="grid grid-cols-1 gap-4">
                                            {fusionReportSummary.entries.map((entry) => (
                                                <div key={entry.timeframe} className="bg-muted/50 p-5 rounded-lg border border-border/20 space-y-3">
                                                    <div className="flex items-center justify-between">
                                                        <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                                                            {formatLabel(entry.timeframe)}
                                                        </div>
                                                        <div className="text-[10px] text-muted-foreground font-bold uppercase">
                                                            Classic · Quant · Pattern
                                                        </div>
                                                    </div>
                                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                                        <div className="bg-muted/50 p-3 rounded-lg border border-border/20">
                                                            <div className="text-[9px] text-muted-foreground font-bold uppercase mb-1">Classic</div>
                                                            <div className="text-sm font-black text-foreground">{formatLabel(entry.classic)}</div>
                                                            <div className="text-[10px] text-muted-foreground">Score {entry.classicScore !== null ? entry.classicScore.toFixed(2) : 'n/a'}</div>
                                                        </div>
                                                        <div className="bg-muted/50 p-3 rounded-lg border border-border/20">
                                                            <div className="text-[9px] text-muted-foreground font-bold uppercase mb-1">Quant</div>
                                                            <div className="text-sm font-black text-foreground">{formatLabel(entry.quant)}</div>
                                                            <div className="text-[10px] text-muted-foreground">Score {entry.quantScore !== null ? entry.quantScore.toFixed(2) : 'n/a'}</div>
                                                        </div>
                                                        <div className="bg-muted/50 p-3 rounded-lg border border-border/20">
                                                            <div className="text-[9px] text-muted-foreground font-bold uppercase mb-1">Pattern</div>
                                                            <div className="text-sm font-black text-foreground">{formatLabel(entry.pattern)}</div>
                                                            <div className="text-[10px] text-muted-foreground">Score {entry.patternScore !== null ? entry.patternScore.toFixed(2) : 'n/a'}</div>
                                                        </div>
                                                    </div>
                                                </div>
                                        ))}
                                    </div>
                                )}

                                {directionScorecardData && scorecardSummary && scorecardSummary.entries.length > 0 && (
                                    <div className="space-y-4">
                                        <div className="flex items-center justify-between">
                                            <div className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground">
                                                Direction Scorecard
                                            </div>
                                            <div className="text-[10px] text-muted-foreground font-bold uppercase">
                                                Model {scorecardSummary.modelVersion ?? 'n/a'} · Neutral {scorecardSummary.neutralThreshold.toFixed(2)}
                                            </div>
                                        </div>
                                        <div className="grid grid-cols-1 gap-4">
                                            {scorecardSummary.entries.map(({ timeframe, frame }) => (
                                                <div key={timeframe} className="bg-muted/50 p-5 rounded-lg border border-border/20 space-y-4">
                                                    <div className="flex items-center justify-between">
                                                        <div className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground">
                                                            {formatLabel(timeframe)}
                                                        </div>
                                                        <div className="text-[10px] text-muted-foreground font-bold uppercase">
                                                            Total {formatContributionValue(frame.total_score)}
                                                        </div>
                                                    </div>
                                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                                        <div className="bg-muted/50 p-3 rounded-lg border border-border/20 space-y-2">
                                                            <div className="text-[9px] text-muted-foreground font-bold uppercase">Classic</div>
                                                            <div className="text-sm font-black text-foreground">{formatLabel(frame.classic_label)}</div>
                                                            <div className="text-[10px] text-muted-foreground">Score {frame.classic_score.toFixed(2)}</div>
                                                            {renderScorecardContributions(frame.contributions?.classic ?? [])}
                                                        </div>
                                                        <div className="bg-muted/50 p-3 rounded-lg border border-border/20 space-y-2">
                                                            <div className="text-[9px] text-muted-foreground font-bold uppercase">Quant</div>
                                                            <div className="text-sm font-black text-foreground">{formatLabel(frame.quant_label)}</div>
                                                            <div className="text-[10px] text-muted-foreground">Score {frame.quant_score.toFixed(2)}</div>
                                                            {renderScorecardContributions(frame.contributions?.quant ?? [])}
                                                        </div>
                                                        <div className="bg-muted/50 p-3 rounded-lg border border-border/20 space-y-2">
                                                            <div className="text-[9px] text-muted-foreground font-bold uppercase">Pattern</div>
                                                            <div className="text-sm font-black text-foreground">{formatLabel(frame.pattern_label)}</div>
                                                            <div className="text-[10px] text-muted-foreground">Score {frame.pattern_score.toFixed(2)}</div>
                                                            {renderScorecardContributions(frame.contributions?.pattern ?? [])}
                                                        </div>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {fusionReportData.alignment_report && Object.keys(fusionReportData.alignment_report).length > 0 && (
                                    <div className="text-xs text-muted-foreground">
                                        Alignment report attached ({Object.keys(fusionReportData.alignment_report).length} fields).
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                </div>
            </div>
            </Card>
        )}

        {verificationReportId && (
            <Card className="overflow-hidden border border-border/30 p-0">
                <Button
                    type="button"
                    variant="ghost"
                    aria-expanded={showVerificationReport}
                    onClick={() =>
                        setShowVerificationReport(!showVerificationReport)
                    }
                    className="h-auto w-full justify-between whitespace-normal rounded-none bg-muted/30 p-4 text-left hover:bg-muted/50"
                >
                    <div className="flex items-center gap-2">
                        <Layers size={14} className="text-muted-foreground" />
                        <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">Verification &amp; Baseline</span>
                    </div>
                    <div className="flex items-center gap-4">
                        {showVerificationReport && isVerificationReportLoading && (
                            <AgentLoadingState
                                type="header"
                                title="Loading Verification Report…"

                            />
                        )}
                        <ChevronDown
                            size={16}
                            className={`text-muted-foreground expandable-chevron ${showVerificationReport ? 'rotate-180' : ''}`}
                        />
                    </div>
                </Button>

                <div
                    className={`expandable-panel ${
                        showVerificationReport ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                    }`}
                >
                    <div className="overflow-hidden">
                        <div className="p-6 space-y-5">
                            {verificationReportError && (
                                <ArtifactLoadError title="Verification report unavailable" error={verificationReportError} {...verificationReportRetry} />
                            )}

                            {!verificationReportData && !verificationReportError && (
                                <ArtifactLoadStatus label="Verification report" isLoading={isVerificationReportLoading} />
                            )}

                            {verificationReportData && (
                                <>
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                        <div className="bg-muted/50 p-4 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">Baseline Gates</div>
                                            <div className="text-lg font-black text-foreground">{verificationSummary?.gatesCount ?? 0}</div>
                                        </div>
                                        <div className="bg-muted/50 p-4 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">Robustness Flags</div>
                                            <div className="text-lg font-black text-foreground">{verificationSummary?.flagsCount ?? 0}</div>
                                        </div>
                                        <div className="bg-muted/50 p-4 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">As Of</div>
                                            <div className="text-lg font-black text-foreground">{verificationReportData.as_of}</div>
                                        </div>
                                    </div>

                                    {verificationReportData.degraded_reasons && verificationReportData.degraded_reasons.length > 0 && (
                                        <div className="flex flex-wrap gap-2">
                                            {verificationReportData.degraded_reasons.map((reason) => (
                                                <span key={reason} className="px-3 py-1 bg-destructive/10 border border-destructive/20 rounded-full text-[10px] font-bold text-destructive uppercase tracking-wider">
                                                    {reason.replace('_', ' ')}
                                                </span>
                                            ))}
                                        </div>
                                    )}

                                    {verificationReportData.robustness_flags && verificationReportData.robustness_flags.length > 0 && (
                                        <div className="flex flex-wrap gap-2">
                                            {verificationReportData.robustness_flags.map((flag) => (
                                                <span key={flag} className="px-3 py-1 bg-warning/10 border border-warning/20 rounded-full text-[10px] font-bold text-warning uppercase tracking-wider">
                                                    {flag.replace('_', ' ')}
                                                </span>
                                            ))}
                                        </div>
                                    )}

                                    {verificationReportData.backtest_summary && (
                                        <div className="bg-muted/50 p-5 rounded-lg border border-border/20 space-y-3">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase">Backtest Summary</div>
                                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-foreground">
                                                <div>Win Rate: {verificationReportData.backtest_summary.win_rate ?? 'n/a'}</div>
                                                <div>Profit Factor: {verificationReportData.backtest_summary.profit_factor ?? 'n/a'}</div>
                                                <div>Sharpe: {verificationReportData.backtest_summary.sharpe_ratio ?? 'n/a'}</div>
                                                <div>Max DD: {verificationReportData.backtest_summary.max_drawdown ?? 'n/a'}</div>
                                                <div>Total Trades: {verificationReportData.backtest_summary.total_trades ?? 'n/a'}</div>
                                            </div>
                                        </div>
                                    )}

                                    {verificationReportData.wfa_summary && (
                                        <div className="bg-muted/50 p-5 rounded-lg border border-border/20 space-y-3">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase">Walk-Forward Summary</div>
                                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-foreground">
                                                <div>WFA Sharpe: {verificationReportData.wfa_summary.wfa_sharpe ?? 'n/a'}</div>
                                                <div>WFE Ratio: {verificationReportData.wfa_summary.wfe_ratio ?? 'n/a'}</div>
                                                <div>Max DD: {verificationReportData.wfa_summary.wfa_max_drawdown ?? 'n/a'}</div>
                                                <div>Periods: {verificationReportData.wfa_summary.period_count ?? 'n/a'}</div>
                                            </div>
                                        </div>
                                    )}

                                    {verificationReportData.baseline_gates && Object.keys(verificationReportData.baseline_gates).length > 0 && (
                                        <div className="bg-muted/50 p-5 rounded-lg border border-border/20">
                                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-3">Baseline Gates</div>
                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs text-foreground">
                                                {Object.entries(verificationReportData.baseline_gates).map(([key, value]) => (
                                                    <div key={key} className="flex items-center justify-between bg-card border border-border/20 rounded-lg px-3 py-2">
                                                        <span className="font-bold uppercase text-[9px] text-muted-foreground">{formatLabel(key)}</span>
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
            </Card>
        )}

        <Card className="space-y-5 border border-border/30 p-5">
            <div className="flex items-center gap-2 mb-6">
                <Layers size={16} className="text-primary" />
                <span className="text-xs font-bold text-muted-foreground uppercase tracking-[0.2em]">Artifact References</span>
            </div>
            {artifactEntries.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {artifactEntries.map(([key, value]) => (
                        <div key={key} className="bg-muted/50 p-4 rounded-lg border border-border/20">
                            <div className="text-[9px] font-bold text-muted-foreground uppercase mb-1">
                                {formatArtifactLabel(key)} ID
                            </div>
                            <div className="text-sm font-mono font-bold text-foreground">{formatArtifactId(value)}</div>
                        </div>
                    ))}
                </div>
            ) : (
                <div className="text-xs text-muted-foreground">No Linked Artifacts Available</div>
            )}
        </Card>
    </section>
);
