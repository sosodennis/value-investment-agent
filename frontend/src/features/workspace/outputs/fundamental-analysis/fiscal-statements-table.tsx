import { Badge } from '@/components/ui/badge';
import { TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { EvidenceSelection } from '../../workspace-evidence-inspector';
import { fiscalPeriodText, type FiscalStatementModel } from './fiscal-statements-model';
import { InspectionValue } from './report-value';

export function FiscalStatementsTable({ report, selectedPeriod, onSelectEvidence }: {
    report: FiscalStatementModel; selectedPeriod: string | null; onSelectEvidence?: (item: EvidenceSelection) => void;
}) {
    return <article aria-label={`${report.frequency === 'quarter' ? 'Quarterly' : 'TTM'} financial statements`} className="min-w-0 space-y-5 rounded-lg border bg-card p-3 @min-[36rem]:p-4">
        <header className="min-w-0 space-y-2">
            <p className="text-xs text-muted-foreground">{report.frequency === 'quarter' ? 'Quarterly' : 'Trailing twelve months'} financial statements</p>
            <h2 tabIndex={-1} className="text-lg font-semibold [overflow-wrap:anywhere]">{report.companyName} · {report.ticker}</h2>
            <p className="text-sm text-muted-foreground">{report.editionLabel} · SEC issuer {report.scope.issuer_id} · {report.scope.security_scope} · {report.scope.currency} · {report.scope.unit}</p>
            <p className="text-sm">Available by {report.cutoffAt}</p>
            <p className="text-xs text-muted-foreground">Actual fiscal dates include 52/53-week calendars. A period label alone does not establish complete or comparable coverage. Valuation eligibility has not been evaluated.</p>
            <p className="text-xs text-muted-foreground">Inspect each value, unavailable entry or conflict. Derived values retain the Service formula and signed inputs. Scroll each table horizontally to compare periods.</p>
        </header>
        {report.tables.map((table) => <section key={table.kind} aria-label={table.title} className="min-w-0 space-y-3">
            <h3 className="font-semibold">{table.title}</h3>
            {table.kind === 'balance_sheet' && <p className="text-xs text-muted-foreground">Balances use the actual instant shown, including for TTM.</p>}
            {table.kind === 'cash_flow' && <p className="text-xs text-muted-foreground">Opening and closing cash are period boundaries. They are not sums of quarterly balances.</p>}
            <div role="region" aria-label={`${table.title} table`} tabIndex={0} className="max-w-full overflow-x-auto rounded-md border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <table className="w-full caption-bottom text-sm">
                    <TableCaption className="px-3 pb-3">{report.scope.currency}. Inspect a cell for full precision, its exact period and original unit.</TableCaption>
                    <TableHeader><TableRow>
                        <TableHead scope="col" className="min-w-44 align-top">Main line item</TableHead>
                        {table.columns.map((column) => <TableHead key={column.id} scope="col" aria-current={selectedPeriod === column.id ? 'true' : undefined} className="min-w-52 align-top aria-current:bg-accent/40">
                            <span className="block font-semibold text-foreground">{column.label}</span>
                            <span className="mt-1 block font-mono text-xs tabular-nums">{column.period ? fiscalPeriodText(column.period) : 'Period unavailable'}</span>
                            {column.period?.kind === 'duration' && <span className="mt-1 block text-xs">Fiscal year starts {column.period.fiscal_year_start}</span>}
                            <span className="mt-2 block text-xs">{column.reported} reported · {column.derived} derived · {column.unavailable} unavailable · {column.conflict} conflicts</span>
                        </TableHead>)}
                    </TableRow></TableHeader>
                    <TableBody>{table.rows.map((row) => <TableRow key={row.id}>
                        <TableHead scope="row" className="whitespace-normal py-3 font-medium text-foreground">{row.label}</TableHead>
                        {row.cells.map((cell) => <TableCell key={cell.id} className="align-top">
                            <InspectionValue evidence={cell.evidence} onSelectEvidence={onSelectEvidence} />
                            <span className="mt-2 block"><Badge variant={cell.kind === 'conflict' || cell.kind === 'unavailable' ? 'warning' : 'outline'}>{cell.kind}</Badge></span>
                            <span className="mt-1 block text-xs text-muted-foreground [overflow-wrap:anywhere]">{cell.reason}</span>
                            <span className="mt-1 block font-mono text-xs text-muted-foreground">{fiscalPeriodText(cell.node.period)}</span>
                        </TableCell>)}
                    </TableRow>)}</TableBody>
                </table>
            </div>
        </section>)}
        <details className="min-w-0 rounded-md border px-3 py-2 text-xs [overflow-wrap:anywhere]">
            <summary className="cursor-pointer font-medium">Reconciliation and cash continuity</summary>
            <ul className="mt-3 space-y-3">{report.reconciliations.map((check) => <li key={`${check.frequency}:${check.period_id}:${check.rule}`}>
                <p>{check.frequency} · {check.rule.replaceAll('_', ' ')} · {check.status.replaceAll('_', ' ')}</p>
                <p>Residual · {check.residual ?? 'Unavailable'} · {check.reason_code?.replaceAll('_', ' ')}</p>
                <p>Period · {check.period_id}</p>
            </li>)}{report.cashContinuities.map((check) => <li key={`${check.window_id}:${check.boundary_date}`}>
                Cash boundary {check.boundary_date} · {check.status.replaceAll('_', ' ')} · {check.reason_code?.replaceAll('_', ' ')}
            </li>)}</ul>
        </details>
        <details className="min-w-0 rounded-md border px-3 py-2 text-xs [overflow-wrap:anywhere]">
            <summary className="cursor-pointer font-medium">Release and saved version</summary>
            <dl className="mt-3 space-y-2">
                <div><dt>Release</dt><dd className="font-mono">{report.releaseDigest}</dd></div>
                <div><dt>Result</dt><dd className="font-mono">{report.resultDigest}</dd></div>
                <div><dt>Selected periods</dt><dd className="font-mono">{report.selectedPeriodSetDigest}</dd></div>
                <div><dt>Candidate</dt><dd className="font-mono">{report.approved.candidate_ref.artifact_id}</dd></div>
                <div><dt>Display decision</dt><dd className="font-mono">{report.approved.decision_ref.artifact_id}</dd></div>
            </dl>
        </details>
    </article>;
}
