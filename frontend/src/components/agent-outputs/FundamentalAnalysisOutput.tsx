import React, { memo } from 'react';
import { LayoutPanelTop, BarChart3 } from 'lucide-react';
import { FinancialTable } from '../FinancialTable';

interface FundamentalAnalysisOutputProps {
    reports: any[];
    resolvedTicker: string | null | undefined;
}

const FundamentalAnalysisOutputComponent: React.FC<FundamentalAnalysisOutputProps> = ({
    reports,
    resolvedTicker
}) => {
    if (reports.length === 0) {
        return (
            <div className="flex-1 flex flex-col items-center justify-center p-12 text-center h-full">
                <BarChart3 size={48} className="text-slate-900 mb-4" />
                <h4 className="text-slate-500 font-bold text-xs uppercase tracking-widest">No Structured Data</h4>
                <p className="text-slate-700 text-[10px] mt-2 max-w-[240px]">
                    Financial reports have not been extracted yet. Please provide a ticker and wait for the Planner to finish extraction.
                </p>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center gap-3 mb-2">
                <LayoutPanelTop size={18} className="text-indigo-400" />
                <h3 className="text-sm font-bold text-white uppercase tracking-widest">Financial Data Matrix</h3>
            </div>
            <FinancialTable
                reports={reports}
                ticker={resolvedTicker || 'N/A'}
            />
        </div>
    );
};

// Export with React.memo for performance optimization
export const FundamentalAnalysisOutput = memo(FundamentalAnalysisOutputComponent);
