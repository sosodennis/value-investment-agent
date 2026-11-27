import { Badge } from '@/components/ui/badge';
import { TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { EvidenceSelection } from '../../workspace-evidence-inspector';
import type { AnnualStatementModel } from './annual-statements-model';
import { InspectionValue } from './report-value';

export function AnnualStatementsTable({ report, selectedPeriod = null, onSelectEvidence }: {
    report: AnnualStatementModel; selectedPeriod?: string | null; onSelectEvidence?: (item: EvidenceSelection) => void;
}) {
    return <article aria-label="Annual financial statements" className="min-w-0 space-y-5 rounded-lg border bg-card p-3 @min-[36rem]:p-4">
        <header className="min-w-0 space-y-2">
            <p className="text-xs text-muted-foreground">Annual financial statements</p>
            <h2 tabIndex={-1} className="text-lg font-semibold [overflow-wrap:anywhere]">{report.companyName} · {report.ticker}</h2>
            <p className="text-sm text-muted-foreground">SEC issuer {report.issuerId} · {report.securityScope} · {report.currency} · {report.unit}</p>
            <p className="text-sm">Available by {report.cutoffAt}</p>
            <Badge variant={report.quality === 'verified' ? 'outline' : 'warning'}>{report.quality}</Badge>
            <p className="text-xs text-muted-foreground">Coverage target · {report.targetYears} annual periods. These are the supported main line items, not complete statements and notes. Valuation eligibility has not been evaluated.</p>
            <p className="text-xs text-muted-foreground">Inspect any value or missing entry for its original value, filing version and selection evidence. Scroll each table horizontally to compare periods.</p>
        </header>
        {report.tables.length === 0 && <p>No statement tables were supplied.</p>}
        {report.tables.map((table) => <section key={table.kind} aria-label={table.title} className="min-w-0 space-y-3">
            <h3 className="font-semibold">{table.title}</h3>
            <div role="region" aria-label={`${table.title} table`} tabIndex={0} className="max-w-full overflow-x-auto rounded-md border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <table className="w-full caption-bottom text-sm">
                    <TableCaption className="px-3 pb-3">{report.currency}. Readable values may use abbreviated units. Inspect a cell for the full precision and reported unit.</TableCaption>
                    <TableHeader><TableRow>
                        <TableHead scope="col" className="min-w-44 align-top">Main line item</TableHead>
                        {table.columns.map((column) => <TableHead scope="col" key={column.id} aria-current={selectedPeriod === column.id ? 'true' : undefined} className="min-w-48 align-top aria-current:bg-accent/40">
                            <span className="block font-semibold text-foreground">{column.label}</span>
                            <span className="mt-1 block font-mono text-xs tabular-nums">{column.period}</span>
                            <span className="mt-1 block text-xs">{column.calendar}{column.days == null ? '' : ` · ${column.days} days`}</span>
                            {column.coverage && <span className="mt-1 block text-xs">{column.coverage.reported_rows}/{column.coverage.declared_rows} rows reported</span>}
                        </TableHead>)}
                    </TableRow></TableHeader>
                    <TableBody>{table.rows.map((row) => <TableRow key={row.id}>
                        <TableHead scope="row" className="whitespace-normal py-3 font-medium text-foreground">{row.label}</TableHead>
                        {row.cells.map((cell) => <TableCell key={cell.id} className="align-top">
                            <InspectionValue evidence={cell.evidence} onSelectEvidence={onSelectEvidence} />
                            <span className="mt-1 block text-xs text-muted-foreground [overflow-wrap:anywhere]">{cell.reason}</span>
                        </TableCell>)}
                    </TableRow>)}</TableBody>
                </table>
            </div>
            <details className="min-w-0 rounded-md border px-3 py-2">
                <summary className="cursor-pointer text-sm font-medium">Reconciliation results ({table.reconciliations.length})</summary>
                <ul className="mt-3 space-y-3 text-xs [overflow-wrap:anywhere]">{table.reconciliations.map((check) => <li key={`${check.period_id}:${check.check_id}`}>
                    <p className="font-medium">{check.periodLabel} · {check.check_id.replaceAll('_', ' ')} · {check.status.replaceAll('_', ' ')} · {check.severity}</p>
                    <p>{check.expression}</p>
                    <p className="font-mono tabular-nums">Difference {check.difference ?? 'unresolved'} · tolerance {check.tolerance ?? 'unresolved'}</p>
                    <p>{check.issue_codes.join(', ') || 'No issue codes'}</p>
                    <p>Inputs · {check.input_fact_ids.join(', ') || 'None'}</p>
                    <p>Policy · {check.policy_version}</p>
                </li>)}</ul>
            </details>
        </section>)}
        <section aria-label="Period comparability" className="space-y-2">
            <h3 className="text-sm font-semibold">Period comparability</h3>
            {report.comparability.length === 0 ? <p className="text-sm text-muted-foreground">No period comparison was supplied.</p> : <ul className="space-y-2 text-xs [overflow-wrap:anywhere]">{report.comparability.map((item) => <li key={`${item.earlier_period_id}:${item.later_period_id}:${item.affected_row_ids.join(',')}`}>
                {item.earlier} to {item.later} · {item.status.replaceAll('_', ' ')} · {item.issue_codes.join(', ') || 'No issue codes'}
                {item.affected_row_ids.length > 0 && <span className="block">Affected rows · {item.affected_row_ids.join(', ')}</span>}
            </li>)}</ul>}
        </section>
        <details className="min-w-0 rounded-md border px-3 py-2 text-xs [overflow-wrap:anywhere]">
            <summary className="cursor-pointer font-medium">Sources and saved version</summary>
            <dl className="mt-3 space-y-2">
                <div><dt>Statement</dt><dd className="font-mono">{report.statementId}</dd></div>
                <div><dt>Data release</dt><dd className="font-mono">{report.releaseDigest}</dd></div>
                <div><dt>Profile</dt><dd>{report.profileId} · {report.profileDigest}</dd></div>
            </dl>
            <ul className="mt-3 space-y-2">{report.sourceOutcomes.map((source) => <li key={source.accession_number}>
                {source.accession_number} · report end {source.report_period_end} · available {source.available_at} · {source.kind}
                {source.kind === 'unavailable' && <p>{source.missing.status} · {source.missing.reason} · {source.issue_codes.join(', ')}</p>}
            </li>)}</ul>
        </details>
    </article>;
}
