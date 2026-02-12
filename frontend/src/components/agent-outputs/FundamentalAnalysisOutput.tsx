import React, { memo } from 'react';
import { LayoutPanelTop, BarChart3 } from 'lucide-react';
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
        'fundamental_output.artifact'
    );

    const hasPreview = !!previewData;
    const reports = artifactData?.financial_reports ?? previewData?.financial_reports ?? [];
    const valuationScore = previewData?.valuation_score;
    const previewKeyMetrics = previewData?.key_metrics ?? {};

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
