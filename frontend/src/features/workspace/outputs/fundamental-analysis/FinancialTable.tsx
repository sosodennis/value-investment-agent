import React, { memo, useMemo } from 'react';
import {
    FinancialReport,
    TraceableField
} from '@/types/agents/fundamental';
import { Info } from 'lucide-react';
import { Card } from '@/components/ui/card';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table';

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
            <TableRow>
                <TableCell className="font-medium text-muted-foreground">{label}</TableCell>
                {sortedReports.map((r, i) => (
                    <TableCell key={i} className="text-right font-mono tabular-nums">
                        <div className="group relative inline-block">
                            {formatter(accessor(r))}
                            {accessor(r)?.provenance && (
                                <div className="invisible group-hover:visible absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 rounded-md border border-border bg-popover p-2 text-left text-xs text-popover-foreground whitespace-pre-wrap break-words">
                                    {accessor(r)?.provenance?.concept ? `XBRL: ${accessor(r)?.provenance?.concept}` : ''}
                                    {accessor(r)?.provenance?.expression ? `Calc: ${accessor(r)?.provenance?.expression}` : ''}
                                    {accessor(r)?.provenance?.description ? `Manual: ${accessor(r)?.provenance?.description}` : ''}
                                </div>
                            )}
                        </div>
                    </TableCell>
                ))}
            </TableRow>
        );
    };

    // Ratios
    const renderRatioRow = (label: string, numAccessor: (r: FinancialReport) => TraceableField | null, denAccessor: (r: FinancialReport) => TraceableField | null) => {
        return (
            <TableRow className="bg-muted/50">
                <TableCell className="font-semibold text-primary">{label}</TableCell>
                {sortedReports.map((r, i) => (
                    <TableCell key={i} className="text-right font-mono font-semibold tabular-nums text-primary">
                        {formatRatio(numAccessor(r), denAccessor(r))}
                    </TableCell>
                ))}
            </TableRow>
        );
    }

    // Determine Type based on first report (robustness check needed?)
    const extensionType = sortedReports[0]?.extension ?
        ('inventory' in sortedReports[0].extension ? 'Industrial' :
            'loans_and_leases' in sortedReports[0].extension ? 'FinancialServices' :
                'real_estate_assets' in sortedReports[0].extension ? 'RealEstate' : null) : null;

    const getIndustrialField = (
        report: FinancialReport,
        field: 'inventory' | 'rd_expense' | 'capex'
    ): TraceableField | null | undefined => {
        const extension = report.extension;
        if (!extension || !('inventory' in extension)) return null;
        return extension[field];
    };

    const getFinancialServicesField = (
        report: FinancialReport,
        field: 'loans_and_leases' | 'deposits' | 'interest_income'
    ): TraceableField | null | undefined => {
        const extension = report.extension;
        if (!extension || !('loans_and_leases' in extension)) return null;
        return extension[field];
    };

    const getRealEstateField = (
        report: FinancialReport,
        field: 'real_estate_assets' | 'ffo'
    ): TraceableField | null | undefined => {
        const extension = report.extension;
        if (!extension || !('real_estate_assets' in extension)) return null;
        return extension[field];
    };

    return (
        <div className="w-full py-2">
            <Card className="overflow-hidden">
                <div className="flex items-center justify-between gap-3 bg-muted/50 px-4 py-3">
                    <h3 className="flex items-center gap-2 font-semibold text-foreground">
                        <Info size={16} className="text-primary" />
                        Financial Health Report: <span className="text-primary">{ticker}</span>
                    </h3>
                    <span className="rounded-md bg-background px-2 py-1 text-xs text-muted-foreground">
                        {extensionType || 'General'} Model
                    </span>
                </div>

                <div className="overflow-x-auto">
                    <Table>
                        <TableHeader>
                            <TableRow className="bg-background hover:bg-background">
                                <TableHead className="min-w-48">Metric</TableHead>
                                {headers.map((h, i) => (
                                    <TableHead key={i} className="text-right tabular-nums">{h}</TableHead>
                                ))}
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {/* Key Ratios */}
                            {renderRatioRow('ROE', (r) => r.base.net_income, (r) => r.base.total_equity)}
                            {renderRatioRow('Debt/Equity', (r) => r.base.total_liabilities, (r) => r.base.total_equity)}

                            <TableRow><TableCell colSpan={headers.length + 1} className="h-2 p-0" /></TableRow>

                            {/* Base Metrics */}
                            {renderRow('Revenue', (r) => r.base.total_revenue)}
                            {renderRow('Net Income', (r) => r.base.net_income)}
                            {renderRow('Op. Cash Flow', (r) => r.base.operating_cash_flow)}
                            {renderRow('Cash & Eq.', (r) => r.base.cash_and_equivalents)}
                            {renderRow('Total Assets', (r) => r.base.total_assets)}
                            {renderRow('Total Liabilities', (r) => r.base.total_liabilities)}
                            {renderRow('Total Equity', (r) => r.base.total_equity)}
                            {renderRow('Shares Outstanding', (r) => r.base.shares_outstanding, formatNumber)}

                            {/* Extension Metrics */}
                            {extensionType === 'Industrial' && (
                                <>
                                    <TableRow><TableCell colSpan={headers.length + 1} className="font-semibold text-muted-foreground">Industrial Metrics</TableCell></TableRow>
                                    {renderRow("Inventory", r => getIndustrialField(r, 'inventory'))}
                                    {renderRow("R&D Info", r => getIndustrialField(r, 'rd_expense'))}
                                    {renderRow("Capex", r => getIndustrialField(r, 'capex'))}
                                </>
                            )}

                            {extensionType === 'FinancialServices' && (
                                <>
                                    <TableRow><TableCell colSpan={headers.length + 1} className="font-semibold text-muted-foreground">Banking Metrics</TableCell></TableRow>
                                    {renderRow("Loans", r => getFinancialServicesField(r, 'loans_and_leases'))}
                                    {renderRow("Deposits", r => getFinancialServicesField(r, 'deposits'))}
                                    {renderRow("Interest Income", r => getFinancialServicesField(r, 'interest_income'))}
                                </>
                            )}

                            {extensionType === 'RealEstate' && (
                                <>
                                    <TableRow><TableCell colSpan={headers.length + 1} className="font-semibold text-muted-foreground">REIT Metrics</TableCell></TableRow>
                                    {renderRow("Real Estate Assets", r => getRealEstateField(r, 'real_estate_assets'))}
                                    {renderRow("FFO", r => getRealEstateField(r, 'ffo'))}
                                </>
                            )}

                        </TableBody>
                    </Table>
                </div>
            </Card>
        </div>
    );
};

// Export with React.memo for performance optimization
export const FinancialTable = memo(FinancialTableComponent);
