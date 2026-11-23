import { useId, useState } from 'react';
import { chartColorCssVariable } from '@/lib/chart-theme';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import type { ExactAmount, FundamentalValuationModel } from './fundamental-report-model';
import { formatReportNumber } from './fundamental-number-format';
import { ExactValue, type EvidenceActionProps } from './report-value';

type Uncertainty = Extract<FundamentalValuationModel['uncertainty'], { kind: 'provided' }>;

type QuantileMark = { kind: 'quantile' | 'base'; label: string; value: ExactAmount };

function QuantileMarkers({ uncertainty, base, onSelectEvidence }: EvidenceActionProps & {
    uncertainty: Uncertainty;
    base: FundamentalValuationModel['base']['perShare'];
}) {
    const [activeId, setActiveId] = useState<string | null>(null);
    const readoutId = useId();
    const marks: QuantileMark[] = uncertainty.quantiles.filter((item) => item.aliasOf === null).map((item) => ({ kind: 'quantile', label: item.label.toUpperCase(), value: item.value }));
    if (base) marks.push({ kind: 'base', label: 'Deterministic base', value: base });
    const coordinates = marks.flatMap((mark) => mark.value.coordinate === null ? [] : [mark.value.coordinate]);
    const magnitude = Math.max(...coordinates.map(Math.abs), 0) || 1;
    const finiteMinimum = coordinates.length ? Math.min(...coordinates.map((value) => value / magnitude)) : 0;
    const finiteMaximum = coordinates.length ? Math.max(...coordinates.map((value) => value / magnitude)) : 0;
    const padding = finiteMinimum === finiteMaximum ? Math.abs(finiteMinimum) * 0.05 || 1 : (finiteMaximum - finiteMinimum) * 0.08;
    const low = finiteMinimum - padding;
    const high = finiteMaximum + padding;
    const position = (value: number) => 100 * ((value / magnitude - low) / (high - low));
    const ticks = finiteMinimum === finiteMaximum ? [finiteMinimum] : [finiteMinimum, (finiteMinimum + finiteMaximum) / 2, finiteMaximum];
    const lower = uncertainty.quantiles.find((item) => item.aliasOf === null && item.label === 'p05')?.value.coordinate;
    const upper = uncertainty.quantiles.find((item) => item.aliasOf === null && item.label === 'p95')?.value.coordinate;
    const active = marks.find((mark) => mark.value.evidence.id === activeId) ?? marks[0];
    const display = (value: ExactAmount) => formatReportNumber(value.raw, { kind: 'per-share', currency: value.currency });
    return <figure aria-label="Service quantile markers" className="@container min-w-0 space-y-3 rounded-md border bg-muted/10 p-3">
        <figcaption className="text-sm font-medium">Valuation quantile range <span className="font-normal text-muted-foreground">· {base?.currency ?? marks[0]?.value.currency} per share</span></figcaption>
        {coordinates.length > 0 ? <>
            {lower != null && upper != null && <div>
                <p className="text-xs text-muted-foreground">P05–P95 interval</p>
                <div className="relative mx-4 mt-1 h-4" role="img" aria-label="Supplied P05–P95 interval">
                    <span className="absolute inset-x-0 top-1/2 border-t" style={{ borderColor: chartColorCssVariable('axisBorder') }} />
                    <span className="absolute top-1 h-2 min-w-px rounded-sm border" style={{ left: `${position(lower)}%`, width: `${Math.max(0, position(upper) - position(lower))}%`, backgroundColor: chartColorCssVariable('overlayBand'), borderColor: chartColorCssVariable('seriesPrimary') }} />
                </div>
            </div>}
            <div className="space-y-2">
                {marks.map((mark) => <div key={mark.value.evidence.id}>
                    <div className="flex flex-wrap justify-between gap-x-3 gap-y-1 text-xs">
                        <span className="font-medium">{mark.label}</span>
                        <span className="whitespace-nowrap font-mono tabular-nums">· {display(mark.value)}</span>
                    </div>
                    {mark.value.coordinate === null ? <button type="button" className="mt-1 rounded-sm text-xs underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={`${onSelectEvidence ? 'Inspect' : 'Read'} ${mark.label} · ${display(mark.value)}`} onFocus={() => setActiveId(mark.value.evidence.id)} onClick={() => { setActiveId(mark.value.evidence.id); onSelectEvidence?.(mark.value.evidence); }}>Value cannot be plotted; inspect the supplied value</button> : <div className="relative mx-4 h-8">
                        <span aria-hidden="true" className="absolute inset-x-0 top-1/2 border-t" style={{ borderColor: chartColorCssVariable('gridLine') }} />
                        <button type="button" className="absolute top-1/2 flex size-8 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-sm outline-none hover:bg-primary/10 focus-visible:ring-2 focus-visible:ring-ring" style={{ left: `${position(mark.value.coordinate)}%` }} aria-label={`${onSelectEvidence ? 'Inspect' : 'Read'} ${mark.label} · ${display(mark.value)}`} aria-describedby={readoutId} onMouseEnter={() => setActiveId(mark.value.evidence.id)} onFocus={() => setActiveId(mark.value.evidence.id)} onClick={() => { setActiveId(mark.value.evidence.id); onSelectEvidence?.(mark.value.evidence); }}>
                            <span aria-hidden="true" className={mark.kind === 'base' ? 'size-3 rotate-45 border-2 border-foreground bg-background' : 'size-3 rounded-full border-2 border-background'} style={mark.kind === 'quantile' ? { backgroundColor: chartColorCssVariable('seriesPrimary') } : undefined} />
                        </button>
                    </div>}
                </div>)}
            </div>
            <div className="relative mx-4 h-8 border-t" style={{ borderColor: chartColorCssVariable('axisBorder') }} aria-label="Valuation per share axis">
                {ticks.map((tick, index) => <span key={index} className={`absolute top-1 whitespace-nowrap font-mono text-xs tabular-nums text-muted-foreground ${ticks.length > 1 && index === 1 ? '@max-[18rem]:hidden' : ''}`} style={{ left: `${100 * (tick - low) / (high - low)}%`, transform: ticks.length === 1 || index === 1 ? 'translateX(-50%)' : index === 0 ? undefined : 'translateX(-100%)' }}>{formatReportNumber(String(tick * magnitude), { kind: 'per-share', currency: '' }, { includeUnit: false })}</span>)}
            </div>
        </> : <div className="space-y-2 text-sm">
            <p className="text-muted-foreground">No finite chart coordinates are available.</p>
            {marks.map((mark) => <p key={mark.value.evidence.id}>{mark.label} · <ExactValue amount={mark.value} onSelectEvidence={onSelectEvidence} /></p>)}
        </div>}
        <p id={readoutId} role="status" aria-label="Valuation selected point" className="min-h-10 text-sm">{active && <><span className="text-muted-foreground">{active.label}</span><span className="ml-2 whitespace-nowrap font-mono tabular-nums">· {display(active.value)}</span></>}</p>
        <p className="text-xs text-muted-foreground">Circles show supplied quantiles. The diamond is the independent deterministic base. Hover or focus a mark to read its value{onSelectEvidence ? '; activate it to inspect its source' : ''}.</p>
    </figure>;
}

export function ValuationUncertainty({
    report,
    onSelectEvidence,
}: EvidenceActionProps & { report: FundamentalValuationModel }) {
    const uncertainty = report.uncertainty;
    return (
        <section aria-label="Model uncertainty" className="space-y-4 border-b pb-5">
            <div className="space-y-1">
                <h3 className="font-semibold">Model uncertainty</h3>
                <p className="text-sm text-muted-foreground">Model outcomes under the service assumptions.</p>
            </div>
            {uncertainty.kind === 'not-requested' ? (
                <p className="text-sm text-muted-foreground">No uncertainty report was supplied.</p>
            ) : (
                <>
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                        <p>
                            {uncertainty.mode === 'sampled'
                                ? 'Monte Carlo sampling'
                                : 'Scenario and sensitivity results · no Monte Carlo samples requested in this result'}
                        </p>
                        <Badge variant={uncertainty.quality === 'verified' ? 'success' : 'warning'}>
                            {uncertainty.quality}
                        </Badge>
                    </div>
                    {uncertainty.quantileBasis !== null && (
                        <div className="rounded-md border border-warning/40 bg-warning/5 p-3 text-sm">
                            <p className="font-medium">Conditional on the retained base hypotheses</p>
                            <p className="mt-1 text-muted-foreground">
                                Revenue growth, operating margin and terminal growth are sampled. Capital and
                                reinvestment hypotheses remain fixed. The scenarios have no assigned probabilities.
                            </p>
                        </div>
                    )}
                    {uncertainty.quantiles.length > 0 ? (
                        <>
                            <QuantileMarkers uncertainty={uncertainty} base={report.base.perShare} onSelectEvidence={onSelectEvidence} />
                            <p className="text-xs text-muted-foreground">
                                Quantiles describe the valuation model under sampled assumptions. They do not
                                estimate future stock prices or investment confidence.
                            </p>
                        </>
                    ) : (
                        <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
                            No quantiles were supplied. The base calculation is shown independently.
                        </p>
                    )}
                    {(uncertainty.convergence.converged === false || uncertainty.invalidReasons.length > 0) && <Alert variant="warning">
                        <AlertTitle>Sampling limitations</AlertTitle>
                        <AlertDescription>
                            {uncertainty.convergence.converged === false && <p>Sampling did not converge.</p>}
                            {uncertainty.invalidReasons.map((reason) => <p key={reason.code}>{reason.code} · {formatReportNumber(String(reason.count), { kind: 'count' })}</p>)}
                        </AlertDescription>
                    </Alert>}
                    <details className="rounded-md border px-3 py-2">
                    <summary className="cursor-pointer text-sm font-medium">Service scenarios and diagnostics</summary>
                    <div className="mt-3 space-y-4">
                    {uncertainty.dominantDrivers.length > 0 && (
                        <div>
                            <h4 className="text-sm font-medium">Dominant drivers</h4>
                            <ul className="mt-2 flex flex-wrap gap-2">
                                {uncertainty.dominantDrivers.map((driver) => (
                                    <li key={driver}>
                                        <Badge variant="secondary">{driver}</Badge>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                    {uncertainty.sensitivity.length > 0 && (
                        <div className="space-y-2">
                            <h4 className="text-sm font-medium">Sensitivity results per share</h4>
                            <p className="text-xs text-muted-foreground">
                                Input coordinates were not supplied in this result. Values are listed in
                                service order.
                            </p>
                            <dl className="grid gap-3 @min-[36rem]:grid-cols-2">
                                {uncertainty.sensitivity.map((row) => (
                                    <div key={row.path} className="min-w-0 rounded-md border p-3">
                                        <dt className="break-words text-xs text-muted-foreground">
                                            {row.path}
                                        </dt>
                                        <dd className="mt-1 [overflow-wrap:anywhere] font-mono text-sm tabular-nums">
                                            {row.values.map((value) => formatReportNumber(value.raw, { kind: 'per-share', currency: report.currency ?? '' })).join(', ')}
                                        </dd>
                                    </div>
                                ))}
                            </dl>
                        </div>
                    )}
                    {uncertainty.scenarios.length > 0 && (
                        <div className="space-y-2">
                            <h4 className="text-sm font-medium">Service scenarios</h4>
                            <p className="text-xs text-muted-foreground">Scenario numbers preserve service order and calculation identity. No probabilities or value-based rankings are assigned.</p>
                            <dl className="grid gap-3 @min-[36rem]:grid-cols-2">
                                {uncertainty.scenarios.map((scenario, index) => (
                                    <div
                                        key={`${scenario.binding.resultHash}:${index}`}
                                        className="min-w-0 rounded-md border p-3"
                                    >
                                        <dt className="text-xs text-muted-foreground">
                                            Scenario {index + 1} · {scenario.status} · {scenario.quality}
                                        </dt>
                                        <dd className="mt-1 text-sm">
                                            <ExactValue amount={scenario.perShare} onSelectEvidence={onSelectEvidence} />
                                            <p className="mt-1 text-xs text-muted-foreground">As of {scenario.valuationDate}</p>
                                            <details className="mt-3 rounded-md border p-2 text-xs">
                                                <summary className="cursor-pointer font-medium">Scenario {index + 1} assumptions and identity</summary>
                                                <p className="mt-2 [overflow-wrap:anywhere]">Result hash · {scenario.binding.resultHash}</p>
                                                <p className="mt-1 [overflow-wrap:anywhere]">Input digest · {scenario.binding.inputDigest}</p>
                                                <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap font-mono [overflow-wrap:anywhere]">{scenario.assumptionsJson}</pre>
                                            </details>
                                        </dd>
                                    </div>
                                ))}
                            </dl>
                        </div>
                    )}
                    <details className="rounded-md border px-3 py-2 text-xs">
                        <summary className="cursor-pointer font-medium">Sampling diagnostics</summary>
                        <div className="mt-3 space-y-2 text-muted-foreground">
                            <p>
                                Samples requested {formatReportNumber(String(uncertainty.requestedSamples), { kind: 'count' })} · valid{' '}
                                {formatReportNumber(String(uncertainty.validSamples), { kind: 'count' })} · invalid {formatReportNumber(String(uncertainty.invalidSamples), { kind: 'count' })}
                            </p>
                            <p>
                                Converged ·{' '}
                                {uncertainty.convergence.converged == null
                                    ? 'Unavailable'
                                    : String(uncertainty.convergence.converged)}{' '}
                                · minimum valid samples{' '}
                                {uncertainty.convergence.minimumValidSamples == null ? 'Unavailable' : formatReportNumber(String(uncertainty.convergence.minimumValidSamples), { kind: 'count' })} · invalid ratio{' '}
                                {uncertainty.convergence.invalidRatio ? formatReportNumber(uncertainty.convergence.invalidRatio.raw, { kind: 'ratio' }) : 'Unavailable'}
                            </p>
                            <p className="[overflow-wrap:anywhere]">
                                Seed {uncertainty.seed ?? 'Unavailable'} · sampler{' '}
                                {uncertainty.samplerVersion ?? 'Unavailable'} · invalid draw policy{' '}
                                {uncertainty.invalidDrawPolicy ?? 'Unavailable'}
                            </p>
                            {uncertainty.quantileBasis !== null && (
                                <div className="space-y-1 [overflow-wrap:anywhere]">
                                    <p>Conditional policy {uncertainty.quantileBasis.policy_version}</p>
                                    <p>Joint scenarios digest {uncertainty.quantileBasis.joint_scenarios_digest}</p>
                                    <p>Conditioning assumptions digest {uncertainty.quantileBasis.conditioning_assumptions_digest}</p>
                                </div>
                            )}
                        </div>
                    </details>
                    </div>
                    </details>
                </>
            )}
        </section>
    );
}
