import { Badge } from '@/components/ui/badge';
import { TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { EvidenceSelection } from '../../workspace-evidence-inspector';
import type { FundamentalFactModel } from './fundamental-report-model';
import { InspectionValue } from './report-value';

export function FinancialFactsTable({ facts, onSelectEvidence }: {
    facts: FundamentalFactModel[];
    onSelectEvidence?: (item: EvidenceSelection) => void;
}) {
    return (
        <section aria-label="Financial data" className="min-w-0 space-y-3 border-b pb-5">
            <h3 className="font-semibold">Financial data</h3>
            <p className="text-sm text-muted-foreground">Selected canonical facts retain their source period, unit, dimensions and scale. This selection does not represent complete historical statements.</p>
            {facts.length === 0 ? <p>No canonical facts were supplied.</p> : (
                <details className="min-w-0 rounded-md border px-3 py-2">
                    <summary className="cursor-pointer text-sm font-medium">All financial facts ({facts.length})</summary>
                    <p className="my-2 text-xs text-muted-foreground">Scroll horizontally for source periods, units, dimensions and quality.</p>
                    <div className="max-w-full overflow-x-auto rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" role="region" aria-label="Financial facts table" tabIndex={0}>
                    <table className="w-full min-w-[72rem] caption-bottom text-sm">
                        <colgroup>
                            <col className="w-[22%]" /><col className="w-[15%]" />
                            <col className="w-[21%]" /><col className="w-[16%]" />
                            <col className="w-[14%]" /><col className="w-[12%]" />
                        </colgroup>
                        <TableCaption>Readable values; inspect any value for full precision. Scale is source metadata.</TableCaption>
                        <TableHeader><TableRow>
                            <TableHead scope="col">Fact</TableHead><TableHead scope="col">Value</TableHead>
                            <TableHead scope="col">Period</TableHead><TableHead scope="col">Unit and scale</TableHead>
                            <TableHead scope="col">Dimensions</TableHead><TableHead scope="col">Quality</TableHead>
                        </TableRow></TableHeader>
                        <TableBody>{facts.map((fact) => <TableRow key={fact.id}>
                            <TableCell className="[overflow-wrap:anywhere]"><span className="block font-medium">{fact.label}</span><span className="text-xs text-muted-foreground">{fact.id}</span></TableCell>
                            <TableCell className={fact.value.kind === 'number' ? 'whitespace-nowrap' : '[overflow-wrap:anywhere]'}><InspectionValue evidence={fact.evidence} onSelectEvidence={onSelectEvidence} /></TableCell>
                            <TableCell className="whitespace-nowrap font-mono text-xs tabular-nums">{fact.period}</TableCell>
                            <TableCell className="[overflow-wrap:anywhere]">{fact.currency && fact.currency !== fact.unit ? `${fact.currency} · ` : ''}{fact.unit} · source scale 10^{fact.scale}</TableCell>
                            <TableCell className="[overflow-wrap:anywhere]">{fact.dimensions.length ? fact.dimensions.map((dimension) => `${dimension.name}: ${dimension.member}`).join(', ') : 'No dimensions'}</TableCell>
                            <TableCell className="[overflow-wrap:anywhere]"><Badge variant={fact.quality === 'verified' ? 'outline' : 'warning'}>{fact.quality}</Badge>{fact.issueCodes.length > 0 && <p className="mt-1 text-xs">{fact.issueCodes.join(', ')}</p>}</TableCell>
                        </TableRow>)}</TableBody>
                    </table>
                    </div>
                </details>
            )}
        </section>
    );
}
