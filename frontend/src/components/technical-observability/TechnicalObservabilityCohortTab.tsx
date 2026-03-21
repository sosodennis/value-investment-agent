'use client';

import type { TechnicalMonitoringAggregateModel } from '@/types/technical-observability';

export type TechnicalObservabilityLabelLens =
    | 'raw_outcomes'
    | 'approved_snapshots';

type TechnicalObservabilityCohortTabProps = {
    aggregates: TechnicalMonitoringAggregateModel[];
    isLoading: boolean;
    error: Error | null;
    labelLens: TechnicalObservabilityLabelLens;
};

export function TechnicalObservabilityCohortTab({
    aggregates,
    isLoading,
    error,
    labelLens,
}: TechnicalObservabilityCohortTabProps) {
    if (labelLens === 'approved_snapshots') {
        return (
            <SemanticBoundaryPanel
                title="Approved snapshots stay separate from raw cohort truth"
                body="This cohort board currently reflects raw outcomes from the truth model. Approved snapshots are versioned governance overlays and will land here only when a snapshot-backed cohort read model is exposed explicitly."
            />
        );
    }

    const grouped = groupAggregatesByTimeframe(aggregates);

    return (
        <div className="grid gap-6">
            {error ? (
                <DegradedPanel
                    title="Cohort analysis is degraded"
                    body={error.message}
                />
            ) : null}

            {isLoading && aggregates.length === 0 ? (
                <LoadingPanel
                    title="Refreshing cohort slices"
                    body="Loading grouped behavior across timeframe, horizon, and logic-version combinations."
                />
            ) : null}

            {!isLoading && aggregates.length === 0 ? (
                <EmptyPanel
                    title="No cohort slices match the current filters"
                    body="Widen the active filters to inspect grouped behavior across more timeframe and horizon buckets."
                />
            ) : null}

            {aggregates.length > 0 ? (
                <>
                    <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                        <SummaryCard
                            label="Cohort Slices"
                            value={String(aggregates.length)}
                            helper="Distinct timeframe / horizon / logic-version groups in the raw truth lens."
                        />
                        <SummaryCard
                            label="Avg Coverage"
                            value={renderAverageCoverage(aggregates)}
                            helper="Average labeled-event coverage across the returned cohort slices."
                        />
                        <SummaryCard
                            label="Avg Forward Return"
                            value={renderAverageMetric(aggregates, 'avg_forward_return', true)}
                            helper="Mean forward return across aggregate slices with resolved raw outcomes."
                        />
                        <SummaryCard
                            label="Avg Realized Vol"
                            value={renderAverageMetric(
                                aggregates,
                                'avg_realized_volatility',
                                false
                            )}
                            helper="Average realized volatility across the same grouped population."
                        />
                    </section>

                    <section className="grid gap-6">
                        {grouped.map((group) => (
                            <article
                                key={group.timeframe}
                                className="rounded-[24px] border border-white/8 bg-[linear-gradient(180deg,rgba(15,23,42,0.82),rgba(2,6,23,0.96))] p-6"
                            >
                                <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
                                    <div>
                                        <div className="text-[10px] font-black uppercase tracking-[0.28em] text-cyan-300">
                                            Cohort Board
                                        </div>
                                        <h3 className="mt-3 text-xl font-black tracking-tight text-white">
                                            {group.timeframe.toUpperCase()} timeframe
                                        </h3>
                                        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                                            Compare horizon and logic-version slices inside the{' '}
                                            {group.timeframe} timeframe without collapsing raw
                                            outcomes into governance labels.
                                        </p>
                                    </div>
                                    <div className="text-sm text-slate-400">
                                        {group.items.length} slices
                                    </div>
                                </div>

                                <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                                    {group.items.map((aggregate) => (
                                        <div
                                            key={`${aggregate.timeframe}-${aggregate.horizon}-${aggregate.logic_version}`}
                                            className="rounded-[24px] border border-white/8 bg-white/3 p-5"
                                        >
                                            <div className="flex items-start justify-between gap-3">
                                                <div>
                                                    <div className="text-sm font-black uppercase tracking-[0.18em] text-white">
                                                        {aggregate.horizon}
                                                    </div>
                                                    <div className="mt-1 text-xs uppercase tracking-[0.18em] text-slate-500">
                                                        {aggregate.logic_version}
                                                    </div>
                                                </div>
                                                <div className="rounded-full border border-cyan-400/20 bg-cyan-500/10 px-3 py-1 text-[11px] font-black uppercase tracking-[0.16em] text-cyan-200">
                                                    {aggregate.event_count} events
                                                </div>
                                            </div>

                                            <dl className="mt-5 space-y-3 text-sm">
                                                <MetricRow
                                                    label="Label Coverage"
                                                    value={renderCoverage(
                                                        aggregate.labeled_event_count,
                                                        aggregate.event_count
                                                    )}
                                                />
                                                <MetricRow
                                                    label="Unresolved Backlog"
                                                    value={String(
                                                        aggregate.unresolved_event_count
                                                    )}
                                                />
                                                <MetricRow
                                                    label="Avg Forward Return"
                                                    value={formatSignedPercent(
                                                        aggregate.avg_forward_return
                                                    )}
                                                />
                                                <MetricRow
                                                    label="Avg MFE / MAE"
                                                    value={`${formatSignedPercent(
                                                        aggregate.avg_mfe
                                                    )} / ${formatSignedPercent(
                                                        aggregate.avg_mae
                                                    )}`}
                                                />
                                                <MetricRow
                                                    label="Avg Realized Vol"
                                                    value={formatDecimal(
                                                        aggregate.avg_realized_volatility
                                                    )}
                                                />
                                            </dl>
                                        </div>
                                    ))}
                                </div>
                            </article>
                        ))}
                    </section>
                </>
            ) : null}
        </div>
    );
}

function groupAggregatesByTimeframe(aggregates: TechnicalMonitoringAggregateModel[]) {
    const map = new Map<string, TechnicalMonitoringAggregateModel[]>();
    for (const aggregate of aggregates) {
        const existing = map.get(aggregate.timeframe);
        if (existing) {
            existing.push(aggregate);
        } else {
            map.set(aggregate.timeframe, [aggregate]);
        }
    }

    return [...map.entries()]
        .sort((left, right) => left[0].localeCompare(right[0]))
        .map(([timeframe, items]) => ({
            timeframe,
            items: [...items].sort((left, right) => {
                const horizonCompare = left.horizon.localeCompare(right.horizon);
                if (horizonCompare !== 0) {
                    return horizonCompare;
                }
                return left.logic_version.localeCompare(right.logic_version);
            }),
        }));
}

function renderAverageCoverage(
    aggregates: TechnicalMonitoringAggregateModel[]
): string {
    if (aggregates.length === 0) {
        return '0%';
    }
    const total = aggregates.reduce(
        (sum, aggregate) => sum + aggregate.labeled_event_count / Math.max(aggregate.event_count, 1),
        0
    );
    return `${Math.round((total / aggregates.length) * 100)}%`;
}

function renderAverageMetric(
    aggregates: TechnicalMonitoringAggregateModel[],
    key:
        | 'avg_forward_return'
        | 'avg_realized_volatility',
    asPercent: boolean
): string {
    const values = aggregates
        .map((aggregate) => aggregate[key])
        .filter((value): value is number => value !== null && value !== undefined);

    if (values.length === 0) {
        return 'n/a';
    }

    const average = values.reduce((sum, value) => sum + value, 0) / values.length;
    return asPercent ? formatSignedPercent(average) : average.toFixed(2);
}

function renderCoverage(labeledCount: number, eventCount: number): string {
    if (eventCount === 0) {
        return '0%';
    }
    return `${Math.round((labeledCount / eventCount) * 100)}%`;
}

function formatSignedPercent(value: number | null | undefined): string {
    if (value === null || value === undefined) {
        return 'n/a';
    }
    const percentage = value * 100;
    const prefix = percentage > 0 ? '+' : '';
    return `${prefix}${percentage.toFixed(2)}%`;
}

function formatDecimal(value: number | null | undefined): string {
    if (value === null || value === undefined) {
        return 'n/a';
    }
    return value.toFixed(2);
}

function SummaryCard({
    label,
    value,
    helper,
}: {
    label: string;
    value: string;
    helper: string;
}) {
    return (
        <article className="rounded-[24px] border border-white/8 bg-slate-950/60 p-5 shadow-[0_18px_48px_rgba(2,6,23,0.24)]">
            <div className="text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">
                {label}
            </div>
            <div className="mt-4 text-3xl font-black tracking-tight text-white">
                {value}
            </div>
            <p className="mt-4 text-sm leading-6 text-slate-400">{helper}</p>
        </article>
    );
}

function MetricRow({ label, value }: { label: string; value: string }) {
    return (
        <div className="flex items-start justify-between gap-4 border-b border-white/6 pb-3 last:border-b-0">
            <div className="text-[11px] font-black uppercase tracking-[0.18em] text-slate-500">
                {label}
            </div>
            <div className="text-right text-sm font-semibold text-slate-100">{value}</div>
        </div>
    );
}

function SemanticBoundaryPanel({
    title,
    body,
}: {
    title: string;
    body: string;
}) {
    return (
        <article className="rounded-[24px] border border-cyan-400/16 bg-cyan-500/8 p-6">
            <div className="text-[10px] font-black uppercase tracking-[0.24em] text-cyan-300">
                Approved Snapshot Lens
            </div>
            <h3 className="mt-3 text-xl font-black tracking-tight text-white">{title}</h3>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300">{body}</p>
        </article>
    );
}

function DegradedPanel({ title, body }: { title: string; body: string }) {
    return (
        <article className="rounded-[24px] border border-amber-400/20 bg-amber-500/10 p-5 text-sm text-amber-50">
            <div className="text-[10px] font-black uppercase tracking-[0.24em] text-amber-300">
                Degraded State
            </div>
            <div className="mt-2 text-base font-black text-white">{title}</div>
            <p className="mt-2 leading-6 text-amber-100/90">{body}</p>
        </article>
    );
}

function LoadingPanel({ title, body }: { title: string; body: string }) {
    return (
        <article className="rounded-[24px] border border-white/8 bg-slate-950/60 p-6">
            <div className="text-[10px] font-black uppercase tracking-[0.24em] text-cyan-300">
                Loading
            </div>
            <h3 className="mt-3 text-xl font-black tracking-tight text-white">{title}</h3>
            <p className="mt-3 text-sm leading-6 text-slate-400">{body}</p>
        </article>
    );
}

function EmptyPanel({ title, body }: { title: string; body: string }) {
    return (
        <article className="rounded-[24px] border border-dashed border-white/12 bg-slate-950/40 p-8">
            <div className="text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">
                Empty State
            </div>
            <h3 className="mt-3 text-xl font-black tracking-tight text-white">{title}</h3>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">{body}</p>
        </article>
    );
}
