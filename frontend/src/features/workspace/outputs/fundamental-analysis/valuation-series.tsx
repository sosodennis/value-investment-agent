import { useId } from 'react';
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { FundamentalReportModel, FundamentalValuationModel } from './fundamental-report-model';
import { formatReportNumber, formatReportSeries } from './fundamental-number-format';
import { projectForecastSeries, projectHistoricalSeries, type ReportSeries } from './fundamental-report-series';
import type { EvidenceActionProps } from './report-value';

function SeriesChart({ series }: { series: ReportSeries }) {
    const coordinates = series.points.flatMap((point) => point.value?.coordinate == null ? [] : [point.value.coordinate]);
    if (coordinates.length === 0) return <p className="text-xs text-muted-foreground">No finite chart coordinates are available. Read the supplied values in the table.</p>;
    const magnitude = Math.max(...coordinates.map(Math.abs)) || 1;
    const low = Math.min(0, ...coordinates.map((value) => value / magnitude));
    const high = Math.max(0, ...coordinates.map((value) => value / magnitude));
    const y = (value: number) => high === low ? 55 : 100 - 85 * ((value / magnitude - low) / (high - low));
    const x = (index: number) => 16 + (268 * index) / Math.max(1, series.points.length - 1);
    return <figure aria-label={`${series.label} trend`} className="min-w-0 rounded-md border bg-muted/10 p-3">
        <figcaption className="mb-2 text-sm font-medium">{series.label} <span className="text-xs font-normal text-muted-foreground">· {series.currency}</span></figcaption>
        <svg viewBox="0 0 300 125" className="h-40 w-full" aria-hidden="true">
            <line x1="16" x2="284" y1={y(0)} y2={y(0)} className="stroke-border" />
            {series.points.map((point, index) => {
                const current = point.value?.coordinate;
                const previous = series.points[index - 1]?.value?.coordinate;
                if (current == null) return null;
                return <g key={point.label}>
                    {previous != null && <line x1={x(index - 1)} y1={y(previous)} x2={x(index)} y2={y(current)} className="stroke-primary" strokeWidth="2" />}
                    <circle cx={x(index)} cy={y(current)} r="3" className="fill-primary stroke-background"><title>{point.label}: {point.value && formatReportNumber(point.value.raw, { kind: 'money', currency: series.currency })}</title></circle>
                </g>;
            })}
        </svg>
        <div className="mb-2 flex justify-between gap-2 text-xs text-muted-foreground">{series.points.map((point) => <span key={point.label} className="min-w-0 [overflow-wrap:anywhere]">{point.label}</span>)}</div>
        <p className="text-xs text-muted-foreground">Separate scale for this series. Supplied values and evidence are in the table; missing points remain gaps.</p>
    </figure>;
}

function SeriesTable({ series, onSelectEvidence, caption }: EvidenceActionProps & { series: ReportSeries[]; caption: string }) {
    const id = useId();
    const labels = series[0]?.points.map((point) => point.label) ?? [];
    const formatted = series.map((item) => formatReportSeries(item.points.flatMap((point) => point.value ? [point.value.raw] : []), { kind: 'money', currency: item.currency }));
    return <div className="space-y-2">
        <p className="text-xs text-muted-foreground">All amounts in {series[0]?.currency} billions (B). Scroll horizontally to read every series.</p>
        <div role="region" aria-label={caption} tabIndex={0} className="max-w-full overflow-x-auto rounded-md border">
            <Table>
                <TableCaption>{caption}. {formatted.some((item) => item.precision === 6) ? 'Small nonzero values extend series precision to six places or scientific notation.' : 'Values are rounded to two decimal places.'}</TableCaption>
                <TableHeader><TableRow><TableHead scope="col">Period</TableHead>{series.map((item) => <TableHead key={item.id} scope="col">{item.label}</TableHead>)}</TableRow></TableHeader>
                <TableBody>{labels.map((label, index) => <TableRow key={label}>
                    <TableHead scope="row">{label}</TableHead>
                    {series.map((item, column) => {
                        const point = item.points[index];
                        const evidence = point?.evidence;
                        const displayValue = point?.value ? formatReportNumber(point.value.raw, { kind: 'money', currency: item.currency }, { moneyScale: 9, includeUnit: false, precision: formatted[column].precision }) : null;
                        return <TableCell key={item.id} className="font-mono tabular-nums">{displayValue !== null && evidence
                            ? onSelectEvidence
                                ? <button type="button" className="rounded-sm text-left underline decoration-dashed underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={`Inspect ${evidence.title}`} aria-describedby={`${id}-${column}-${index}`} onClick={() => onSelectEvidence({ ...evidence, displayValue: `${displayValue} ${item.currency} B` })}><span id={`${id}-${column}-${index}`}>{displayValue}<span className="sr-only"> {item.currency} B</span></span></button>
                                : displayValue
                            : <span className="text-muted-foreground">Unavailable</span>}</TableCell>;
                    })}
                </TableRow>)}</TableBody>
            </Table>
        </div>
    </div>;
}

export function ValuationForecast({ report, onSelectEvidence }: EvidenceActionProps & { report: FundamentalValuationModel }) {
    const series = projectForecastSeries(report);
    const hasValues = series.some((item) => item.points.some((point) => point.value !== null));
    return <section aria-label="Five-year forecast" className="min-w-0 space-y-3 border-b pb-5">
        <h3 className="font-semibold">Five-year forecast</h3>
        <p className="text-sm text-muted-foreground">Service calculation nodes from this deterministic base. Year 1–5 are forecast ordinals; calendar years were not supplied.</p>
        {hasValues ? <>
            <div className="grid min-w-0 gap-3 @min-[44rem]:grid-cols-2">{series.map((item) => <SeriesChart key={item.id} series={item} />)}</div>
            <SeriesTable series={series} caption="Forecast annual values" onSelectEvidence={onSelectEvidence} />
        </> : <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">No supported five-year revenue or FCFF nodes were supplied. No forecast was inferred.</p>}
    </section>;
}

export function ValuationHistory({ report, onSelectEvidence }: EvidenceActionProps & { report: FundamentalReportModel }) {
    const history = projectHistoricalSeries(report);
    return <section aria-label="Comparable history" className="min-w-0 space-y-3 border-b pb-5">
        <h3 className="font-semibold">Comparable history</h3>
        <p className="text-sm text-muted-foreground">Historical facts are separate from forecasts. Trends require comparable annual scope, units, dimensions, coverage and filing versions.</p>
        {history.map((item) => item.kind === 'comparable' ? <div key={item.series.id} className="space-y-3">
            <SeriesChart series={item.series} />
            <SeriesTable series={[item.series]} caption={`${item.series.label} historical period-end values`} onSelectEvidence={onSelectEvidence} />
            <p className="text-xs text-muted-foreground">Source periods · {item.periods.join('; ')}</p>
        </div> : <div key={item.id} className="rounded-md border border-dashed p-3">
            <h4 className="text-sm font-medium">{item.label} · trend unavailable</h4>
            <p className="mt-1 text-xs text-muted-foreground">{item.reasons.join(' ')} Full facts remain available below.</p>
        </div>)}
    </section>;
}
