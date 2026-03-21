'use client';

import { AlertTriangle, CheckCircle2, Clock3, Layers3 } from 'lucide-react';

import type {
    TechnicalCalibrationObservationBuildResultModel,
    TechnicalMonitoringAggregateModel,
    TechnicalMonitoringRowModel,
    TechnicalObservabilityFilters,
} from '@/types/technical-observability';

type TechnicalObservabilityOverviewTabProps = {
    filters: TechnicalObservabilityFilters;
    aggregates: TechnicalMonitoringAggregateModel[];
    rows: TechnicalMonitoringRowModel[];
    calibrationReadiness: TechnicalCalibrationObservationBuildResultModel | null;
    isLoading: boolean;
    error: Error | null;
};

export function TechnicalObservabilityOverviewTab({
    filters,
    aggregates,
    rows,
    calibrationReadiness,
    isLoading,
    error,
}: TechnicalObservabilityOverviewTabProps) {
    const totalEvents = aggregates.reduce(
        (sum, aggregate) => sum + aggregate.event_count,
        0
    );
    const totalLabeled = aggregates.reduce(
        (sum, aggregate) => sum + aggregate.labeled_event_count,
        0
    );
    const totalUnresolved = aggregates.reduce(
        (sum, aggregate) => sum + aggregate.unresolved_event_count,
        0
    );
    const qualityFlaggedRows = rows.filter(
        (row) => row.data_quality_flags.length > 0
    ).length;
    const labelCoverage =
        totalEvents === 0 ? '0%' : `${Math.round((totalLabeled / totalEvents) * 100)}%`;
    const unresolvedRows = rows.filter((row) => row.resolved_at === null).slice(0, 6);
    const topCohorts = [...aggregates]
        .sort((left, right) => right.event_count - left.event_count)
        .slice(0, 5);
    const dropEntries = Object.entries(calibrationReadiness?.dropped_reasons ?? {}).sort(
        (left, right) => right[1] - left[1]
    );

    return (
        <div className="grid gap-6">
            {error ? (
                <StatusBanner
                    tone="degraded"
                    title="Read model returned a degraded response"
                    body={error.message}
                />
            ) : null}

            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <OverviewStatCard
                    icon={Layers3}
                    label="Total Events"
                    value={String(totalEvents)}
                    helper="Prediction events matched by the current shared filters."
                />
                <OverviewStatCard
                    icon={CheckCircle2}
                    label="Label Coverage"
                    value={labelCoverage}
                    helper={`${totalLabeled} labeled rows across the active event scope.`}
                />
                <OverviewStatCard
                    icon={Clock3}
                    label="Unresolved Backlog"
                    value={String(totalUnresolved)}
                    helper="Events still waiting on matured outcome collection."
                />
                <OverviewStatCard
                    icon={AlertTriangle}
                    label="Quality Flagged Rows"
                    value={String(qualityFlaggedRows)}
                    helper="Rows carrying data-quality annotations in the truth model."
                />
            </section>

            {isLoading && totalEvents === 0 && rows.length === 0 ? (
                <OverviewLoadingState />
            ) : null}

            {!isLoading && totalEvents === 0 && rows.length === 0 ? (
                <EmptyStatePanel
                    title="No observability data matches the current scope"
                    body="Try widening the date range, clearing ticker filters, or switching back to all horizons to inspect the broader monitoring surface."
                />
            ) : null}

            {totalEvents > 0 || rows.length > 0 ? (
                <section className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
                    <article className="rounded-[24px] border border-white/8 bg-[linear-gradient(180deg,rgba(15,23,42,0.82),rgba(2,6,23,0.96))] p-6">
                        <SectionKicker kicker="Backlog Watchlist" />
                        <h3 className="mt-3 text-xl font-black tracking-tight text-white">
                            Outcome collection pressure points
                        </h3>
                        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                            These unresolved events are still waiting for raw outcome
                            collection under the current shared filter scope.
                        </p>

                        {unresolvedRows.length === 0 ? (
                            <EmptyMiniState text="No unresolved events in the current filtered rows." />
                        ) : (
                            <div className="mt-5 space-y-3">
                                {unresolvedRows.map((row) => (
                                    <div
                                        key={row.event_id}
                                        className="rounded-2xl border border-white/8 bg-white/3 p-4"
                                    >
                                        <div className="flex flex-wrap items-start justify-between gap-3">
                                            <div>
                                                <div className="text-sm font-black uppercase tracking-[0.18em] text-cyan-200">
                                                    {row.ticker} · {row.direction}
                                                </div>
                                                <div className="mt-2 text-xs uppercase tracking-[0.2em] text-slate-500">
                                                    {row.timeframe} / {row.horizon} /{' '}
                                                    {row.logic_version}
                                                </div>
                                            </div>
                                            <div className="text-right text-xs text-slate-400">
                                                <div>{formatDateTime(row.event_time)}</div>
                                                <div className="mt-1 uppercase tracking-[0.2em] text-amber-300">
                                                    Pending outcome
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </article>

                    <div className="grid gap-6">
                        <article className="rounded-[24px] border border-white/8 bg-slate-950/70 p-6">
                            <SectionKicker kicker="Cohort Pulse" />
                            <h3 className="mt-3 text-lg font-black tracking-tight text-white">
                                Highest-volume truth buckets
                            </h3>
                            {topCohorts.length === 0 ? (
                                <EmptyMiniState text="No aggregate cohorts are available yet." />
                            ) : (
                                <div className="mt-5 space-y-3">
                                    {topCohorts.map((aggregate) => (
                                        <div
                                            key={`${aggregate.timeframe}-${aggregate.horizon}-${aggregate.logic_version}`}
                                            className="rounded-2xl border border-white/8 bg-white/3 p-4"
                                        >
                                            <div className="flex items-start justify-between gap-3">
                                                <div>
                                                    <div className="text-sm font-semibold text-white">
                                                        {aggregate.timeframe} / {aggregate.horizon}
                                                    </div>
                                                    <div className="mt-1 text-xs uppercase tracking-[0.18em] text-slate-500">
                                                        {aggregate.logic_version}
                                                    </div>
                                                </div>
                                                <div className="text-right">
                                                    <div className="text-lg font-black text-cyan-200">
                                                        {aggregate.event_count}
                                                    </div>
                                                    <div className="text-xs uppercase tracking-[0.18em] text-slate-500">
                                                        events
                                                    </div>
                                                </div>
                                            </div>
                                            <div className="mt-3 text-xs text-slate-400">
                                                Coverage {renderCoverage(
                                                    aggregate.labeled_event_count,
                                                    aggregate.event_count
                                                )}{' '}
                                                · backlog {aggregate.unresolved_event_count}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </article>

                        <article className="rounded-[24px] border border-white/8 bg-slate-950/70 p-6">
                            <SectionKicker kicker="Labeling Health" />
                            <h3 className="mt-3 text-lg font-black tracking-tight text-white">
                                Readiness and drop signals
                            </h3>
                            <dl className="mt-5 space-y-4">
                                <InfoLine
                                    label="Applied Tickers"
                                    value={
                                        filters.tickers.length > 0
                                            ? filters.tickers.join(', ')
                                            : 'All tracked tickers'
                                    }
                                />
                                <InfoLine
                                    label="Calibration Usable Rows"
                                    value={String(
                                        calibrationReadiness?.usable_row_count ?? 0
                                    )}
                                />
                                <InfoLine
                                    label="Dropped Rows"
                                    value={String(
                                        calibrationReadiness?.dropped_row_count ?? 0
                                    )}
                                />
                                <InfoLine
                                    label="Top Drop Reason"
                                    value={
                                        dropEntries.length === 0
                                            ? 'No dropped rows'
                                            : `${dropEntries[0][0]} (${dropEntries[0][1]})`
                                    }
                                />
                            </dl>
                        </article>
                    </div>
                </section>
            ) : null}
        </div>
    );
}

type OverviewStatCardProps = {
    icon: React.ComponentType<{ className?: string }>;
    label: string;
    value: string;
    helper: string;
};

function OverviewStatCard({
    icon: Icon,
    label,
    value,
    helper,
}: OverviewStatCardProps) {
    return (
        <article className="rounded-[24px] border border-white/8 bg-slate-950/60 p-5 shadow-[0_18px_48px_rgba(2,6,23,0.24)]">
            <div className="flex items-start justify-between gap-3">
                <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">
                        {label}
                    </div>
                    <div className="mt-4 text-3xl font-black tracking-tight text-white">
                        {value}
                    </div>
                </div>
                <div className="rounded-2xl bg-cyan-500/12 p-3 text-cyan-200">
                    <Icon className="h-5 w-5" />
                </div>
            </div>
            <p className="mt-4 text-sm leading-6 text-slate-400">{helper}</p>
        </article>
    );
}

function OverviewLoadingState() {
    return (
        <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
            <article className="rounded-[24px] border border-white/8 bg-slate-950/60 p-6">
                <SectionKicker kicker="Loading" />
                <h3 className="mt-3 text-xl font-black tracking-tight text-white">
                    Refreshing monitoring summary
                </h3>
                <p className="mt-3 text-sm leading-6 text-slate-400">
                    Pulling aggregates, unresolved rows, and readiness metadata from the
                    DB truth model.
                </p>
            </article>
            <article className="rounded-[24px] border border-white/8 bg-slate-950/60 p-6">
                <SectionKicker kicker="Loading" />
                <p className="mt-3 text-sm leading-6 text-slate-400">
                    Event-level investigation panels will populate as soon as the read
                    model response settles.
                </p>
            </article>
        </div>
    );
}

type StatusBannerProps = {
    tone: 'degraded';
    title: string;
    body: string;
};

function StatusBanner({ title, body }: StatusBannerProps) {
    return (
        <div className="rounded-[24px] border border-amber-400/20 bg-amber-500/10 p-5 text-sm text-amber-50">
            <div className="text-[10px] font-black uppercase tracking-[0.24em] text-amber-300">
                Degraded State
            </div>
            <div className="mt-2 text-base font-black text-white">{title}</div>
            <p className="mt-2 leading-6 text-amber-100/90">{body}</p>
        </div>
    );
}

type EmptyStatePanelProps = {
    title: string;
    body: string;
};

function EmptyStatePanel({ title, body }: EmptyStatePanelProps) {
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

function EmptyMiniState({ text }: { text: string }) {
    return (
        <div className="mt-5 rounded-2xl border border-dashed border-white/10 bg-white/3 p-4 text-sm leading-6 text-slate-400">
            {text}
        </div>
    );
}

function SectionKicker({ kicker }: { kicker: string }) {
    return (
        <div className="text-[10px] font-black uppercase tracking-[0.28em] text-cyan-300">
            {kicker}
        </div>
    );
}

function InfoLine({ label, value }: { label: string; value: string }) {
    return (
        <div className="flex items-start justify-between gap-4 border-b border-white/6 pb-3 last:border-b-0">
            <dt className="text-[11px] font-black uppercase tracking-[0.2em] text-slate-500">
                {label}
            </dt>
            <dd className="text-right text-sm font-semibold text-slate-100">{value}</dd>
        </div>
    );
}

function renderCoverage(labeledCount: number, eventCount: number): string {
    if (eventCount === 0) {
        return '0%';
    }
    return `${Math.round((labeledCount / eventCount) * 100)}%`;
}

function formatDateTime(value: string): string {
    return new Date(value).toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        timeZone: 'UTC',
        timeZoneName: 'short',
    });
}
