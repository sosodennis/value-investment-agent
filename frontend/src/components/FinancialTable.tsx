import React, { memo, useMemo } from 'react';
import {
    FinancialReport,
    TraceableField,
    IndustrialExtension,
    FinancialServicesExtension,
    RealEstateExtension
} from '@/types/agents/fundamental';
import { Info } from 'lucide-react';

interface FinancialTableProps {
    reports: FinancialReport[];
    ticker: string;
}

const FinancialTableComponent: React.FC<FinancialTableProps> = ({ reports, ticker }) => {
    // Memoize sorted reports to prevent recalculation on every render
    const sortedReports = useMemo(() => {
        if (!reports || reports.length === 0) return [];
        return [...reports].sort((a, b) => {
            const yearA = parseInt(String(a.base.fiscal_year?.value || 0));
            const yearB = parseInt(String(b.base.fiscal_year?.value || 0));
            return yearB - yearA;
        });
    }, [reports]);

    const headers = useMemo(() => sortedReports.map(r => {
        const fy = r.base.fiscal_year?.value || 'N/A';
        const fp = r.base.fiscal_period?.value || 'N/A';
        return `${fy} (${fp})`;
    }), [sortedReports]);

    // Early return if no data
    if (sortedReports.length === 0) return null;

    const formatCurrency = (field: TraceableField | null | undefined) => {
        if (!field || field.value === null || field.value === undefined) return '-';
        try {
            const val = parseFloat(String(field.value));
            if (isNaN(val)) return String(field.value);

            // Format large numbers
            if (Math.abs(val) >= 1e9) return `$${(val / 1e9).toFixed(2)}B`;
            if (Math.abs(val) >= 1e6) return `$${(val / 1e6).toFixed(2)}M`;
            return `$${val.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
        } catch {
            return String(field.value);
        }
    };

    const formatNumber = (field: TraceableField | null | undefined) => {
        if (!field || field.value === null || field.value === undefined) return '-';
        try {
            const val = parseFloat(String(field.value));
            if (isNaN(val)) return String(field.value);
            return val.toLocaleString(undefined, { maximumFractionDigits: 0 });
        } catch {
            return String(field.value);
        }
    };

    const formatRatio = (num: TraceableField | null, den: TraceableField | null) => {
        const n = num?.value ? parseFloat(String(num.value)) : 0;
        const d = den?.value ? parseFloat(String(den.value)) : 0;

        if (!n || !d) return '-';
        return (n / d).toFixed(2);
    }

    const renderRow = (label: string, accessor: (r: FinancialReport) => TraceableField | null | undefined, formatter = formatCurrency) => {
        return (
            <tr className="border-b border-slate-800 hover:bg-slate-800/50 transition-colors">
                <td className="py-3 px-4 text-slate-400 text-sm font-medium">{label}</td>
                {sortedReports.map((r, i) => (
                    <td key={i} className="py-3 px-4 text-slate-200 text-sm text-right font-mono">
                        <div className="group relative inline-block">
                            {formatter(accessor(r))}
                            {accessor(r)?.provenance && (
                                <div className="invisible group-hover:visible absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 p-2 bg-slate-900 border border-slate-700 rounded shadow-xl text-[10px] text-slate-400 whitespace-pre-wrap break-words text-left">
                                    {accessor(r)?.provenance?.concept ? `XBRL: ${accessor(r)?.provenance?.concept}` : ''}
                                    {accessor(r)?.provenance?.expression ? `Calc: ${accessor(r)?.provenance?.expression}` : ''}
                                    {accessor(r)?.provenance?.description ? `Manual: ${accessor(r)?.provenance?.description}` : ''}
                                </div>
                            )}
                        </div>
                    </td>
                ))}
            </tr>
        );
    };

    // Ratios
    const renderRatioRow = (label: string, numAccessor: (r: FinancialReport) => TraceableField | null, denAccessor: (r: FinancialReport) => TraceableField | null) => {
        return (
            <tr className="border-b border-slate-800 hover:bg-slate-800/50 transition-colors bg-slate-900/30">
                <td className="py-3 px-4 text-indigo-400 text-sm font-bold">{label}</td>
                {sortedReports.map((r, i) => (
                    <td key={i} className="py-3 px-4 text-indigo-300 text-sm text-right font-mono font-bold">
                        {formatRatio(numAccessor(r), denAccessor(r))}
                    </td>
                ))}
            </tr>
        );
    }

    // Determine Type based on first report (robustness check needed?)
    const extensionType = sortedReports[0]?.extension ?
        ('inventory' in sortedReports[0].extension ? 'Industrial' :
            'loans_and_leases' in sortedReports[0].extension ? 'FinancialServices' :
                'real_estate_assets' in sortedReports[0].extension ? 'RealEstate' : null) : null;

    return (
        <div className="w-full mt-4 mb-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
            <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
                <div className="px-6 py-4 border-b border-slate-800 bg-slate-950 flex justify-between items-center">
                    <h3 className="text-slate-200 font-semibold flex items-center gap-2">
                        <Info size={16} className="text-blue-500" />
                        Financial Health Report: <span className="text-indigo-400">{ticker}</span>
                    </h3>
                    <span className="text-[10px] text-slate-500 bg-slate-900 px-2 py-1 rounded border border-slate-800 uppercase tracking-wider">
                        {extensionType || 'General'} Model
                    </span>
                </div>

                <div className="overflow-x-auto">
                    <table className="w-full">
                        <thead>
                            <tr className="bg-slate-950/50">
                                <th className="text-left py-3 px-4 text-xs font-bold text-slate-500 uppercase tracking-wider">Metric</th>
                                {headers.map((h, i) => (
                                    <th key={i} className="text-right py-3 px-4 text-xs font-bold text-slate-500 uppercase tracking-wider">{h}</th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {/* Key Ratios */}
                            {renderRatioRow("ROE", r => r.base.net_income, r => r.base.total_equity)}
                            {renderRatioRow("Debt/Equity", r => r.base.total_liabilities, r => r.base.total_equity)}

                            <tr className="bg-slate-800/20"><td colSpan={headers.length + 1} className="py-1"></td></tr>

                            {/* Base Metrics */}
                            {renderRow("Revenue", r => r.base.total_revenue)}
                            {renderRow("Net Income", r => r.base.net_income)}
                            {renderRow("Op. Cash Flow", r => r.base.operating_cash_flow)}
                            {renderRow("Cash & Eq.", r => r.base.cash_and_equivalents)}
                            {renderRow("Total Assets", r => r.base.total_assets)}
                            {renderRow("Total Liabilities", r => r.base.total_liabilities)}
                            {renderRow("Total Equity", r => r.base.total_equity)}
                            {renderRow("Shares Outstanding", r => r.base.shares_outstanding, formatNumber)}

                            {/* Extension Metrics */}
                            {extensionType === 'Industrial' && (
                                <>
                                    <tr className="bg-slate-800/20"><td colSpan={headers.length + 1} className="py-2 px-4 text-xs font-bold text-slate-500 uppercase">Industrial Metrics</td></tr>
                                    {renderRow("Inventory", r => (r.extension as IndustrialExtension)?.inventory)}
                                    {renderRow("R&D Info", r => (r.extension as IndustrialExtension)?.rd_expense)}
                                    {renderRow("Capex", r => (r.extension as IndustrialExtension)?.capex)}
                                </>
                            )}

                            {extensionType === 'FinancialServices' && (
                                <>
                                    <tr className="bg-slate-800/20"><td colSpan={headers.length + 1} className="py-2 px-4 text-xs font-bold text-slate-500 uppercase">Banking Metrics</td></tr>
                                    {renderRow("Loans", r => (r.extension as FinancialServicesExtension)?.loans_and_leases)}
                                    {renderRow("Deposits", r => (r.extension as FinancialServicesExtension)?.deposits)}
                                    {renderRow("Interest Income", r => (r.extension as FinancialServicesExtension)?.interest_income)}
                                </>
                            )}

                            {extensionType === 'RealEstate' && (
                                <>
                                    <tr className="bg-slate-800/20"><td colSpan={headers.length + 1} className="py-2 px-4 text-xs font-bold text-slate-500 uppercase">REIT Metrics</td></tr>
                                    {renderRow("Real Estate Assets", r => (r.extension as RealEstateExtension)?.real_estate_assets)}
                                    {renderRow("FFO", r => (r.extension as RealEstateExtension)?.ffo)}
                                </>
                            )}

                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
};

// Export with React.memo for performance optimization
export const FinancialTable = memo(FinancialTableComponent);
