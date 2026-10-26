import React, { memo } from 'react';
import { Shield, Target, AlertTriangle, TrendingUp, TrendingDown, Minus, Info, CheckCircle2, Zap, Gavel } from 'lucide-react';
import { parseDebateArtifact } from '@/types/agents/artifact-parsers';
import { DebateTranscript } from './DebateTranscript';
import { DebateFactSheet } from './DebateFactSheet';
import { ArtifactReference, AgentStatus } from '@/types/agents';
import { useArtifact } from '../../../../hooks/useArtifact';
import { DebatePreview } from '@/types/preview';
import { AgentLoadingState } from '../shared/AgentLoadingState';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import type { BadgeProps } from '@/components/ui/badge';

interface DebateOutputProps {
    reference: ArtifactReference | null;
    previewData: DebatePreview | null;
    resolvedTicker?: string | null;
    status: AgentStatus;
}

const DebateOutputComponent: React.FC<DebateOutputProps> = ({
    reference,
    previewData,
    resolvedTicker,
    status
}) => {
    type DirectionStyles = {
        tone: string;
        badgeVariant: NonNullable<BadgeProps['variant']>;
        accentBar: string;
        icon: React.ReactNode;
    };
    const { data: artifactData, isLoading: isArtifactLoading, error: artifactError } = useArtifact(
        reference,
        parseDebateArtifact,
        'debate_output.artifact',
        'debate_final_report'
    );

    const isPreviewOnly = !artifactData && !!previewData;
    const hasData = !!artifactData || isPreviewOnly;

    if ((status === 'error' || artifactError) && !hasData) {
        const message = artifactError instanceof Error
            ? artifactError.message
            : 'The debate report could not be loaded.';
        return (
            <Alert variant="destructive" role="alert">
                <AlertTriangle aria-hidden="true" className="size-4" />
                <AlertTitle>Debate report unavailable</AlertTitle>
                <AlertDescription>{message}</AlertDescription>
            </Alert>
        );
    }

    if ((status !== 'done' && !hasData) || (!artifactData && !isPreviewOnly)) {
        return (
            <AgentLoadingState
                type="full"
                icon={Gavel}
                title="Debate in Progress…"
                description="Wait for the debate between Bull and Bear agents to conclude."
                status={status}
            />
        );
    }

    const conclusion = artifactData;
    const direction = artifactData?.final_verdict || 'NEUTRAL';
    const directionLabel = artifactData?.final_verdict ?? (isPreviewOnly ? 'Preview' : 'Not reported');
    const scenarios = artifactData?.scenario_analysis;

    const getDirectionStyles = (): DirectionStyles => {
        switch (direction) {
            case 'STRONG_LONG':
                return {
                    tone: 'text-success',
                    badgeVariant: 'success',
                    accentBar: 'bg-success/50',
                    icon: <TrendingUp size={20} className="text-success" />,
                };
            case 'LONG':
                return {
                    tone: 'text-success',
                    badgeVariant: 'success',
                    accentBar: 'bg-success/40',
                    icon: <TrendingUp size={20} className="text-success" />,
                };
            case 'STRONG_SHORT':
                return {
                    tone: 'text-destructive',
                    badgeVariant: 'destructive',
                    accentBar: 'bg-destructive/50',
                    icon: <TrendingDown size={20} className="text-destructive" />,
                };
            case 'SHORT':
                return {
                    tone: 'text-destructive',
                    badgeVariant: 'destructive',
                    accentBar: 'bg-destructive/40',
                    icon: <TrendingDown size={20} className="text-destructive" />,
                };
            case 'AVOID':
                return {
                    tone: 'text-warning',
                    badgeVariant: 'warning',
                    accentBar: 'bg-warning/40',
                    icon: <AlertTriangle size={20} className="text-warning" />,
                };
            default:
                return {
                    tone: 'text-muted-foreground',
                    badgeVariant: 'outline',
                    accentBar: 'bg-border/40',
                    icon: <Minus size={20} className="text-muted-foreground" />,
                };
        }
    };

    const styles = getDirectionStyles();
    const isReferenceLoading = reference && isArtifactLoading && !artifactData;

    return (
        <div className="space-y-6  pb-12">
            <div className="flex items-center justify-between mb-6 px-2">
                <div className="flex items-center gap-3">
                    <Gavel size={18} className="text-warning" />
                    <h3 className="text-xs font-bold text-muted-foreground uppercase tracking-[0.2em]">Debate Council</h3>
                </div>
                <div className="flex items-center gap-2">
                    {isReferenceLoading && (
                        <AgentLoadingState type="header" title="Loading verdict…" />
                    )}
                    {conclusion?.debate_rounds !== undefined && (
                        <Badge variant="outline">{conclusion.debate_rounds} rounds</Badge>
                    )}
                </div>
            </div>

            <Card className="relative overflow-hidden p-4 sm:p-5">
                <div className={`absolute inset-y-0 left-0 w-0.5 ${styles.accentBar}`} />
                <div className="absolute top-0 right-0 p-4">
                    <Badge variant="outline" className="max-w-40 whitespace-normal text-right">
                        {conclusion?.risk_profile?.replace('_', ' ')}
                    </Badge>
                </div>

                <div className="flex items-center justify-between mb-8">
                    <div className="flex items-center gap-3">
                        <Shield size={18} className="text-warning" />
                        <h3 className="text-xs font-bold text-muted-foreground uppercase tracking-[0.2em]">Investment Verdict</h3>
                    </div>
                    <div className="flex items-center gap-2">
                        <Badge variant={styles.badgeVariant}>{directionLabel}</Badge>
                        {conclusion?.data_quality_warning && (
                            <Badge variant="warning" className="gap-1">
                                <AlertTriangle size={10} /> Data Alert
                            </Badge>
                        )}
                    </div>
                </div>

                <div className="space-y-6 mb-8">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="rounded-lg border border-border/10 bg-muted/50 p-4 relative">
                            <div className="absolute inset-y-0 left-0 w-0.5 bg-warning/70" />
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">Reward/Risk Ratio</span>
                                <span className="text-warning font-black text-xl">
                                    {conclusion?.rr_ratio !== undefined ? `${conclusion.rr_ratio.toFixed(2)}x` : 'Not reported'}
                                </span>
                            </div>
                            <div className="text-[8px] text-muted-foreground uppercase tracking-widest font-mono">
                                {isPreviewOnly ? 'ASYMMETRY CALC_PENDING' : 'WTD_UPSIDE vs WTD_DOWNSIDE'}
                            </div>
                        </div>

                        <div className="rounded-lg border border-border/10 bg-muted/50 p-4 relative">
                            <div className="absolute inset-y-0 left-0 w-0.5 bg-primary/70" />
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">Edge (Alpha)</span>
                                <span className={`${conclusion?.alpha === undefined ? 'text-muted-foreground' : conclusion.alpha > 0 ? 'text-success' : conclusion.alpha < 0 ? 'text-destructive' : 'text-foreground'} font-semibold text-xl tabular-nums`}>
                                    {conclusion?.alpha !== undefined ? (conclusion.alpha * 100).toFixed(1) + '%' : 'N/A'}
                                </span>
                            </div>
                            <div className="text-[8px] text-muted-foreground uppercase tracking-widest font-mono">
                                {isPreviewOnly ? 'Preview value' : conclusion?.risk_free_benchmark !== undefined ? `vs ${(conclusion.risk_free_benchmark * 400).toFixed(1)}% benchmark` : 'Benchmark not reported'}
                            </div>
                        </div>
                    </div>

                    {isPreviewOnly ? (
                        <div className="rounded-lg border border-border/10 bg-muted/50 p-5">
                            <div className="flex items-center gap-3 mb-3">
                                <Zap size={14} className="text-warning" />
                                <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">Verdict Summary (Simulation)</span>
                            </div>
                            <p className="text-sm text-muted-foreground italic leading-relaxed font-serif">
                                &quot;{previewData?.verdict_display || 'Calculating probability cases…'}&quot;
                            </p>
                            <p className="text-[9px] text-muted-foreground mt-3 font-mono">
                                {previewData?.debate_rounds_display}
                            </p>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            <div className="space-y-2">
                                <div className="flex justify-between text-[10px] font-black uppercase tracking-widest">
                                    <span className="text-success flex items-center gap-1.5">
                                        <div className="w-1.5 h-1.5 rounded-full bg-success" />
                                        Bull Case ({scenarios?.bull_case?.price_implication})
                                    </span>
                                    <span className="text-success">{scenarios?.bull_case?.probability}%</span>
                                </div>
                                <div className="h-1.5 w-full bg-card rounded-full overflow-hidden border border-border/20">
                                    <div className="h-full bg-success " style={{ width: `${scenarios?.bull_case?.probability}%` }} />
                                </div>
                                <p className="text-[10px] text-muted-foreground leading-relaxed italic">&quot;{scenarios?.bull_case?.outcome_description}&quot;</p>
                            </div>

                            <div className="space-y-2 opacity-80">
                                <div className="flex justify-between text-[10px] font-black uppercase tracking-widest">
                                    <span className="text-muted-foreground flex items-center gap-1.5">
                                        <div className="w-1.5 h-1.5 rounded-full bg-muted" />
                                        Base Case (Neutral)
                                    </span>
                                    <span className="text-muted-foreground">{scenarios?.base_case?.probability}%</span>
                                </div>
                                <div className="h-1 w-full bg-card rounded-full overflow-hidden border border-border/20">
                                    <div className="h-full bg-muted" style={{ width: `${scenarios?.base_case?.probability}%` }} />
                                </div>
                                <p className="text-[10px] text-muted-foreground leading-relaxed italic">&quot;{scenarios?.base_case?.outcome_description}&quot;</p>
                            </div>

                            <div className="space-y-2">
                                <div className="flex justify-between text-[10px] font-black uppercase tracking-widest">
                                    <span className="text-destructive flex items-center gap-1.5">
                                        <div className="w-1.5 h-1.5 rounded-full bg-destructive" />
                                        Bear Case ({scenarios?.bear_case?.price_implication})
                                    </span>
                                    <span className="text-destructive">{scenarios?.bear_case?.probability}%</span>
                                </div>
                                <div className="h-1.5 w-full bg-card rounded-full overflow-hidden border border-border/20">
                                    <div className="h-full bg-destructive " style={{ width: `${scenarios?.bear_case?.probability}%` }} />
                                </div>
                                <p className="text-[10px] text-destructive leading-relaxed italic">&quot;{scenarios?.bear_case?.outcome_description}&quot;</p>
                            </div>
                        </div>
                    )}
                </div>

                <div className="h-px bg-muted/50 mb-6" />

                <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
                    <div className="flex items-center gap-3">
                        <span className="text-muted-foreground">Conviction</span>
                        <span className={`${styles.tone} tabular-nums`}>{conclusion?.conviction !== undefined ? `${conclusion.conviction}%` : 'Not reported'}</span>
                    </div>
                    <div className="flex items-center gap-3">
                        <span className="text-muted-foreground">Model</span>
                        <span className="text-foreground">{conclusion?.model_summary || 'Not reported'}</span>
                    </div>
                </div>
            </Card>

            <div className="grid grid-cols-1 gap-6">
                <Card className="relative overflow-hidden p-4 sm:p-5">
                    <div className="absolute top-0 right-0 p-8 opacity-[0.03] group-hover:opacity-[0.1] transition-opacity duration-700">
                        <Shield size={160} />
                    </div>
                    <div className="flex items-center gap-3 mb-5 relative z-10">
                        <div className="p-2 rounded-lg bg-success/10 border border-success/20">
                            <CheckCircle2 size={16} className="text-success" />
                        </div>
                        <h4 className="text-[10px] font-bold text-success uppercase tracking-[0.2em]">Dominant Thesis</h4>
                    </div>
                    <p className="text-base text-foreground leading-relaxed font-black tracking-tight relative z-10 italic">
                        &quot;{isPreviewOnly ? previewData?.thesis_display : artifactData?.winning_thesis}&quot;
                    </p>
                </Card>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <Card className="p-4">
                        <div className="flex items-center gap-3 mb-4">
                            <div className="p-2 rounded-lg bg-primary/10 border border-primary/20">
                                <Target size={16} className="text-primary" />
                            </div>
                            <h4 className="text-[10px] font-bold text-primary uppercase tracking-[0.2em]">Primary Catalyst</h4>
                        </div>
                        <p className="text-sm text-muted-foreground leading-relaxed">
                            {isPreviewOnly ? previewData?.catalyst_display : artifactData?.primary_catalyst}
                        </p>
                    </Card>

                    <Card className="p-4">
                        <div className="flex items-center gap-3 mb-4">
                            <div className="p-2 rounded-lg bg-destructive/10 border border-destructive/20">
                                <AlertTriangle size={16} className="text-destructive" />
                            </div>
                            <h4 className="text-[10px] font-bold text-destructive uppercase tracking-[0.2em]">Risk Vectors</h4>
                        </div>
                        <p className="text-sm text-muted-foreground leading-relaxed font-medium">
                            {isPreviewOnly ? previewData?.risk_display : artifactData?.primary_risk}
                        </p>
                    </Card>
                </div>
            </div>

            <Card className="p-4">
                <div className="flex items-center gap-2 mb-6">
                    <Info size={14} className="text-muted-foreground" />
                    <h4 className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">Supporting Audit Factors</h4>
                </div>
                <div className="space-y-3">
                    {conclusion?.supporting_factors?.map((factor: string, i: number) => (
                        <div key={i} className="flex gap-3 text-xs text-muted-foreground transition-colors p-3 bg-muted/50 rounded-lg border border-border/20">
                            <div className="w-1.5 h-1.5 rounded-full bg-muted mt-1.5 shrink-0" />
                            <p className="leading-relaxed">{factor}</p>
                        </div>
                    ))}
                    {(!conclusion?.supporting_factors || conclusion.supporting_factors.length === 0) && (
                        <p className="text-[10px] text-muted-foreground italic">No Secondary Factors Recorded</p>
                    )}
                </div>
            </Card>

            {resolvedTicker ? <p className="text-sm text-muted-foreground">Ticker: <span className="font-mono text-foreground">{resolvedTicker}</span></p> : null}

            {/* Debate Transcript (History) */}
            {artifactData?.history && artifactData.history.length > 0 && (
                <DebateTranscript history={artifactData.history} />
            )}

            {/* Fact Registry */}
            {artifactData?.facts && artifactData.facts.length > 0 && (
                <DebateFactSheet facts={artifactData.facts} />
            )}
        </div>
    );
};

export const DebateOutput = memo(DebateOutputComponent);
