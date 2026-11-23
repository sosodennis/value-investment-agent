import { useId, useState } from 'react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, XAxis, YAxis } from 'recharts';
import { chartColorCssVariable } from '@/lib/chart-theme';
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { FundamentalReportModel, FundamentalValuationModel } from './fundamental-report-model';
import { formatReportNumber, formatReportSeries } from './fundamental-number-format';
import { projectForecastSeries, projectHistoricalSeries, type ReportSeries } from './fundamental-report-series';
import type { EvidenceActionProps } from './report-value';

function SeriesChart({ series, onSelectEvidence }: EvidenceActionProps & { series: ReportSeries }) {
    const [activeIndex, setActiveIndex] = useState(0);
    const readoutId = useId();
    const coordinates = series.points.flatMap((point) => point.value?.coordinate == null ? [] : [point.value.coordinate]);
    if (coordinates.length === 0) return <p className="text-xs text-muted-foreground">No finite chart coordinates are available. Read the supplied values in the table.</p>;
    const magnitude = Math.max(...coordinates.map(Math.abs)) || 1;
    const minimum = Math.min(0, ...coordinates.map((value) => value / magnitude));
    const maximum = Math.max(0, ...coordinates.map((value) => value / magnitude));
    const domain = minimum === maximum ? [-1, 1] : [minimum, maximum];
    const points = series.points.map((point) => ({ label: point.label, coordinate: point.value?.coordinate == null ? null : point.value.coordinate / magnitude }));
    const active = series.points[activeIndex]?.value ? series.points[activeIndex] : series.points.find((point) => point.value !== null);
    const display = (raw: string) => formatReportNumber(raw, { kind: 'money', currency: series.currency });
    return <figure aria-label={`${series.label} trend`} className="min-w-0 rounded-md border bg-muted/10 p-3">
        <figcaption className="text-sm font-medium">{series.label}</figcaption>
        <p className="mb-1 text-xs text-muted-foreground">{series.currency} billions (B) · separate scale</p>
        <div className="h-52 min-w-0">
            <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 400, height: 208 }}>
                <LineChart data={points} margin={{ top: 18, right: 18, bottom: 4, left: 0 }}>
                    <CartesianGrid vertical={false} stroke={chartColorCssVariable('gridLineSoft')} />
                    <XAxis dataKey="label" tick={{ fontSize: 12, fill: chartColorCssVariable('axisText') }} axisLine={{ stroke: chartColorCssVariable('axisBorder') }} tickLine={false} minTickGap={12} interval="preserveStartEnd" />
                    <YAxis width={62} domain={domain} tick={{ fontSize: 12, fill: chartColorCssVariable('axisText') }} axisLine={false} tickLine={false} tickFormatter={(value: number) => formatReportNumber(String(value * magnitude), { kind: 'money', currency: series.currency }, { moneyScale: 9, includeUnit: false })} />
                    <Line dataKey="coordinate" type="linear" connectNulls={false} isAnimationActive={false} stroke={chartColorCssVariable('seriesPrimary')} strokeWidth={2} activeDot={false} dot={({ cx, cy, index }: { cx?: number; cy?: number; index?: number }) => {
                        const point = index === undefined ? undefined : series.points[index];
                        if (cx == null || cy == null || index == null || !point?.value || point.value.coordinate === null) return <g key={index} />;
                        const evidence = point.evidence;
                        return <foreignObject key={point.label} x={cx - 14} y={cy - 14} width={28} height={28} overflow="visible">
                            <button type="button" className="flex size-7 items-center justify-center rounded-full outline-none hover:bg-primary/10 focus-visible:ring-2 focus-visible:ring-ring" aria-label={`${onSelectEvidence && evidence ? 'Inspect' : 'Read'} ${series.label} · ${point.label} · ${display(point.value.raw)}`} aria-describedby={readoutId} onMouseEnter={() => setActiveIndex(index)} onFocus={() => setActiveIndex(index)} onClick={() => { setActiveIndex(index); if (onSelectEvidence && evidence) onSelectEvidence(evidence); }}>
                                <span aria-hidden="true" className="size-2.5 rounded-full border-2 border-background" style={{ backgroundColor: chartColorCssVariable('seriesPrimary') }} />
                            </button>
                        </foreignObject>;
                    }} />
                </LineChart>
            </ResponsiveContainer>
        </div>
        <p id={readoutId} role="status" aria-label={`${series.label} selected point`} className="min-h-10 text-sm">
            {active?.value && <><span className="text-muted-foreground">{active.period ?? active.label}</span><span className="ml-2 whitespace-nowrap font-mono tabular-nums">{display(active.value.raw)}</span></>}
        </p>
        <p className="text-xs text-muted-foreground">Hover or focus a point to read its value{onSelectEvidence ? '; activate it to inspect its source' : ''}. Missing points remain gaps.</p>
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
                    <TableHead scope="row" className="whitespace-nowrap">{label}{series[0]?.points[index]?.period && <span className="block text-xs font-normal text-muted-foreground">{series[0].points[index].period}</span>}</TableHead>
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
    const timeline = report.base.forecastTimeline.kind === 'dated' ? report.base.forecastTimeline.timeline : null;
    return <section aria-label="Five-year forecast" className="min-w-0 space-y-3 border-b pb-5">
        <h3 className="font-semibold">Five-year forecast</h3>
        <p className="text-sm text-muted-foreground">{timeline
            ? 'Forecasts use the annual periods supplied by the service. E means estimated; the year labels identify period-end calendar years.'
            : 'Service calculation nodes from this deterministic base. Year 1–5 are forecast ordinals; calendar years were not supplied.'}</p>
        {timeline && <div className="space-y-2 rounded-md border bg-muted/10 p-3 text-xs text-muted-foreground">
            <p>Revenue and FCFF cover complete annual periods. Future FCFF included covers {timeline.periods[0].included_start} onward, after the valuation date of {timeline.valuation_date} (UTC, end of day).</p>
            <p>FCFF accrues uniformly through each year and settles at year end. This assumption does not use observed year-to-date cash flows. Discounting uses actual days / 365 (ACT/365F).</p>
            <p>Terminal value uses the final full-year FCFF and the annual Gordon growth approximation at the final period end, then discounts back to the valuation date. The model is uncalibrated.</p>
            <details><summary className="cursor-pointer rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Forecast periods and included coverage</summary>
                <ul className="mt-2 space-y-1">{timeline.periods.map((period) => <li key={period.ordinal} className="font-mono tabular-nums">{period.period_start} → {period.period_end} · included {period.included_start} → {period.period_end} ({period.included_days}/{period.full_period_days} days)</li>)}</ul>
            </details>
        </div>}
        {hasValues ? <>
            <div className="grid min-w-0 gap-3 @min-[44rem]:grid-cols-2">{series.filter((item) => item.id !== 'included_fcff').map((item) => <SeriesChart key={item.id} series={item} onSelectEvidence={onSelectEvidence} />)}</div>
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
            <SeriesChart series={item.series} onSelectEvidence={onSelectEvidence} />
            <SeriesTable series={[item.series]} caption={`${item.series.label} historical period-end values`} onSelectEvidence={onSelectEvidence} />
            <p className="text-xs text-muted-foreground">Source periods · {item.periods.join('; ')}</p>
        </div> : <div key={item.id} className="rounded-md border border-dashed p-3">
            <h4 className="text-sm font-medium">{item.label} · trend unavailable</h4>
            <p className="mt-1 text-xs text-muted-foreground">{item.reasons.join(' ')} Full facts remain available below.</p>
        </div>)}
    </section>;
}
