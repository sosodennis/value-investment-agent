import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { EvidenceSelection } from '../../workspace-evidence-inspector';
import type { FundamentalFactModel } from './fundamental-report-model';

export function FinancialFactsTable({ facts, onSelectEvidence }: {
    facts: FundamentalFactModel[];
    onSelectEvidence?: (item: EvidenceSelection) => void;
}) {
    return (
        <section aria-label="Financial data" className="min-w-0 space-y-3 border-b pb-5">
            <h3 className="font-semibold">Financial data</h3>
            <p className="text-sm text-muted-foreground">Selected canonical facts retain their source period, unit, dimensions and scale. This selection does not represent complete historical statements.</p>
            {facts.length === 0 ? <p>No canonical facts were supplied.</p> : (
                <div className="overflow-x-auto">
                    <Table>
                        <TableCaption>Canonical values in base units. Scale is source metadata.</TableCaption>
                        <TableHeader><TableRow>
                            <TableHead scope="col">Fact</TableHead><TableHead scope="col">Exact value</TableHead>
                            <TableHead scope="col">Period</TableHead><TableHead scope="col">Unit and scale</TableHead>
                            <TableHead scope="col">Dimensions</TableHead><TableHead scope="col">Quality</TableHead>
                        </TableRow></TableHeader>
                        <TableBody>{facts.map((fact) => <TableRow key={fact.id}>
                            <TableCell><span className="block font-medium">{fact.label}</span><span className="text-xs text-muted-foreground">{fact.id}</span></TableCell>
                            <TableCell className="break-all font-mono tabular-nums">{onSelectEvidence ? (
                                <button type="button" className="rounded-sm text-left underline decoration-dashed underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => onSelectEvidence(fact.evidence)} aria-label={`Inspect ${fact.label} evidence`}>{fact.value}</button>
                            ) : fact.value}</TableCell>
                            <TableCell>{fact.period}</TableCell>
                            <TableCell>{fact.currency && fact.currency !== fact.unit ? `${fact.currency} · ` : ''}{fact.unit} · source scale 10^{fact.scale}</TableCell>
                            <TableCell>{fact.dimensions.length ? fact.dimensions.map((dimension) => `${dimension.name}: ${dimension.member}`).join(', ') : 'No dimensions'}</TableCell>
                            <TableCell><Badge variant={fact.quality === 'verified' ? 'outline' : 'warning'}>{fact.quality}</Badge>{fact.issueCodes.length > 0 && <p className="mt-1 text-xs">{fact.issueCodes.join(', ')}</p>}</TableCell>
                        </TableRow>)}</TableBody>
                    </Table>
                </div>
            )}
        </section>
    );
}
