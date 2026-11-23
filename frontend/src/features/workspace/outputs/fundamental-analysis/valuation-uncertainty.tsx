import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import type { FundamentalValuationModel } from './fundamental-report-model';
import { ExactValue, type EvidenceActionProps } from './report-value';

type Uncertainty = Extract<FundamentalValuationModel['uncertainty'], { kind: 'provided' }>;

function QuantileMarkers({
    uncertainty,
    base,
}: {
    uncertainty: Uncertainty;
    base: FundamentalValuationModel['base']['perShare'];
}) {
    const points = uncertainty.quantiles.filter((item) => item.aliasOf === null).flatMap((item) =>
        item.value.coordinate === null
            ? []
            : [{ label: item.label, coordinate: item.value.coordinate, raw: item.value.raw }],
    );
    const values = points.map((point) => point.coordinate);
    if (base?.coordinate != null) values.push(base.coordinate);
    const magnitude = Math.max(...values.map(Math.abs));
    if (points.length < 2 || !magnitude) return null;
    const minimum = Math.min(...values.map((value) => value / magnitude));
    const maximum = Math.max(...values.map((value) => value / magnitude));
    if (minimum === maximum) return null;
    const position = (value: number) => 8 + 84 * ((value / magnitude - minimum) / (maximum - minimum));
    const basePosition = base?.coordinate == null ? null : position(base.coordinate);
    return (
        <figure aria-label="Service quantile markers" className="rounded-md border bg-muted/10 px-3 py-2">
            <svg viewBox="0 0 100 20" className="h-20 w-full" aria-hidden="true">
                <line x1="8" x2="92" y1="10" y2="10" className="stroke-border" strokeWidth="0.5" />
                {points.map((point) => (
                    <circle
                        key={point.label}
                        cx={position(point.coordinate)}
                        cy="10"
                        r="1.3"
                        className="fill-primary stroke-background"
                        strokeWidth="0.5"
                    >
                        <title>
                            {point.label}: {point.raw}
                        </title>
                    </circle>
                ))}
                {basePosition !== null && (
                    <path
                        d={`M ${basePosition} 7.5 l 2.5 2.5 l -2.5 2.5 l -2.5 -2.5 Z`}
                        className="fill-background stroke-foreground"
                        strokeWidth="0.6"
                    />
                )}
            </svg>
            <figcaption className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span>
                    <span aria-hidden="true" className="mr-1 inline-block size-2 rounded-full bg-primary" />
                    Service quantiles
                </span>
                {basePosition !== null && (
                    <span>
                        <span
                            aria-hidden="true"
                            className="mr-1 inline-block size-2 rotate-45 border border-foreground"
                        />
                        Deterministic base
                    </span>
                )}
                <span>Values and evidence below</span>
            </figcaption>
        </figure>
    );
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
                            <QuantileMarkers uncertainty={uncertainty} base={report.base.perShare} />
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
                            {uncertainty.invalidReasons.map((reason) => <p key={reason.code}>{reason.code} · {reason.count}</p>)}
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
                                            {row.values.map((value) => value.raw).join(', ')}{' '}
                                            {report.currency} / share
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
                                Samples requested {uncertainty.requestedSamples} · valid{' '}
                                {uncertainty.validSamples} · invalid {uncertainty.invalidSamples}
                            </p>
                            <p>
                                Converged ·{' '}
                                {uncertainty.convergence.converged == null
                                    ? 'Unavailable'
                                    : String(uncertainty.convergence.converged)}{' '}
                                · minimum valid samples{' '}
                                {uncertainty.convergence.minimumValidSamples ?? 'Unavailable'} · invalid ratio{' '}
                                {uncertainty.convergence.invalidRatio?.raw ?? 'Unavailable'}
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
