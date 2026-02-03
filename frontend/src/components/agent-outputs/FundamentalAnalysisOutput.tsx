import React, { memo } from 'react';
import { LayoutPanelTop, BarChart3, Loader2 } from 'lucide-react';
import { FinancialTable } from '../FinancialTable';
import { AgentStatus, StandardAgentOutput } from '@/types/agents';
import { FundamentalAnalysisSuccess } from '@/types/agents/fundamental';
import { useArtifact } from '../../hooks/useArtifact';

interface FundamentalAnalysisOutputProps {
    output: StandardAgentOutput | null;
    resolvedTicker: string | null | undefined;
    status: AgentStatus;
}

const FundamentalAnalysisOutputComponent: React.FC<FundamentalAnalysisOutputProps> = ({
    output,
    resolvedTicker,
    status
}) => {
    // 1. Determine if we have a reference to fetch
    const reference = (output as any)?.reference || (output as any)?.artifact?.reference;
    const preview = (output as any)?.preview || (output as any)?.artifact?.preview || (output as any);

    // 2. Fetch artifact if reference exists
    const { data: artifactData, isLoading: isArtifactLoading } = useArtifact<FundamentalAnalysisSuccess>(
        reference?.artifact_id
    );

    // 3. Resolve the actual data (Artifact > Preview)
    const effectiveData = artifactData || preview;

    const reports = effectiveData?.financial_reports || [];

    // Preview Logic: If we only have preview, show a summary
    const hasPreview = !!preview;
    const valuationScore = preview?.valuation_score;

    if (status !== 'done' && reports.length === 0 && !hasPreview) {
        return (
            <div className="flex-1 flex flex-col items-center justify-center p-12 text-center h-full">
                <BarChart3 size={48} className="text-slate-900 mb-4 animate-pulse opacity-50" />
                <h4 className="text-slate-500 font-bold text-xs uppercase tracking-widest">Processing Financials...</h4>
                <p className="text-slate-700 text-[10px] mt-2 max-w-[240px]">
                    Extracting and analyzing financial data from 10-K/10-Q reports.
                </p>
                <p className="text-[10px] text-slate-500 mt-2">Status: {status}</p>
            </div>
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
                    <div className="flex items-center gap-2 text-[10px] text-indigo-400 font-bold uppercase tracking-widest animate-pulse">
                        <Loader2 size={12} className="animate-spin" />
                        <span>Loading Reports...</span>
                    </div>
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

                    {preview.key_metrics && Object.keys(preview.key_metrics).length > 0 && (
                        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                            {Object.entries(preview.key_metrics).map(([label, value]) => (
                                <div key={label} className="tech-card p-4 group hover:bg-slate-900/40">
                                    <div className="text-label mb-1 text-slate-600 group-hover:text-slate-400 transition-colors">{label}</div>
                                    <div className="text-sm font-black text-white">
                                        {typeof value === 'string' ? value : String(value)}
                                    </div>
                                </div>
                            ))}
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
                <div className="p-8 border border-slate-800 rounded-xl bg-slate-900/30 text-center">
                    <p className="text-slate-500 text-xs italic">
                        {isReferenceLoading ? "Loading financial reports..." : "No financial reports generated."}
                    </p>
                </div>
            )}
        </div>
    );
};

// Export with React.memo for performance optimization
export const FundamentalAnalysisOutput = memo(FundamentalAnalysisOutputComponent);
