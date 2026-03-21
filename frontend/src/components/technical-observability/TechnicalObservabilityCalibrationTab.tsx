'use client';

import type { TechnicalCalibrationObservationBuildResultModel } from '@/types/technical-observability';

import type { TechnicalObservabilityLabelLens } from './TechnicalObservabilityCohortTab';

type TechnicalObservabilityCalibrationTabProps = {
    calibrationReadiness: TechnicalCalibrationObservationBuildResultModel | null;
    isLoading: boolean;
    error: Error | null;
    labelLens: TechnicalObservabilityLabelLens;
};

export function TechnicalObservabilityCalibrationTab({
    calibrationReadiness,
    isLoading,
    error,
    labelLens,
}: TechnicalObservabilityCalibrationTabProps) {
    if (labelLens === 'approved_snapshots') {
        return (
            <SemanticBoundaryPanel
                title="Calibration readiness is intentionally raw-truth scoped"
                body="Approved label snapshots govern versioned labels, but calibration readiness here measures whether the raw truth model has enough usable observations to support fitting. Those are related views, not interchangeable metrics."
            />
        );
    }

    if (error) {
        return (
            <DegradedPanel
                title="Calibration readiness is degraded"
                body={error.message}
            />
        );
    }

    if (isLoading && calibrationReadiness === null) {
        return (
            <LoadingPanel
                title="Refreshing readiness summary"
                body="Pulling candidate rows, usable samples, and drop reasons from the calibration observation builder."
            />
        );
    }

    if (!isLoading && calibrationReadiness === null) {
        return (
            <EmptyPanel
                title="No calibration readiness summary is available"
                body="The current filter scope does not yet return a calibration observation summary."
            />
        );
    }

    if (calibrationReadiness === null) {
        return null;
    }

    const readinessRatio =
        calibrationReadiness.row_count === 0
            ? '0%'
            : `${Math.round(
                  (calibrationReadiness.usable_row_count /
                      calibrationReadiness.row_count) *
                      100
              )}%`;
    const directionGroups = groupObservationsByDirection(
        calibrationReadiness.observations ?? []
    );
    const dropEntries = Object.entries(calibrationReadiness.dropped_reasons).sort(
        (left, right) => right[1] - left[1]
    );

    return (
        <div className="grid gap-6">
            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <SummaryCard
                    label="Candidate Rows"
                    value={String(calibrationReadiness.row_count)}
                    helper="Rows evaluated by the calibration observation builder."
                />
                <SummaryCard
                    label="Usable Rows"
                    value={String(calibrationReadiness.usable_row_count)}
                    helper="Rows currently eligible for calibration observation output."
                />
                <SummaryCard
                    label="Dropped Rows"
                    value={String(calibrationReadiness.dropped_row_count)}
                    helper="Rows rejected before calibration fitting due to missing truth or guardrails."
                />
                <SummaryCard
                    label="Readiness Ratio"
                    value={readinessRatio}
                    helper="Share of candidate rows that are already calibration-usable."
                />
            </section>

            <section className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
                <article className="rounded-[24px] border border-white/8 bg-[linear-gradient(180deg,rgba(15,23,42,0.82),rgba(2,6,23,0.96))] p-6">
                    <div className="text-[10px] font-black uppercase tracking-[0.28em] text-cyan-300">
                        Sample Sufficiency
                    </div>
                    <h3 className="mt-3 text-xl font-black tracking-tight text-white">
                        Builder-ready calibration depth
                    </h3>
                    <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                        Monitor whether enough raw-truth observations exist before any
                        future recalibration workflow is considered.
                    </p>

                    {directionGroups.length === 0 ? (
                        <EmptyMiniState text="Detailed observations are not included in the current readiness payload." />
                    ) : (
                        <div className="mt-6 space-y-3">
                            {directionGroups.map((group) => (
                                <div
                                    key={group.direction}
                                    className="rounded-2xl border border-white/8 bg-white/3 p-4"
                                >
                                    <div className="flex items-start justify-between gap-3">
                                        <div>
                                            <div className="text-sm font-black uppercase tracking-[0.18em] text-white">
                                                {group.direction}
                                            </div>
                                            <div className="mt-1 text-xs uppercase tracking-[0.18em] text-slate-500">
                                                {group.count} observations
                                            </div>
                                        </div>
                                        <div className="text-right text-sm text-slate-300">
                                            avg target {group.averageTargetOutcome}
                                        </div>
                                    </div>
                                    <div className="mt-4 flex flex-wrap gap-2">
                                        {group.windows.map((window) => (
                                            <span
                                                key={`${group.direction}-${window}`}
                                                className="rounded-full border border-cyan-400/20 bg-cyan-500/10 px-3 py-1 text-xs font-black uppercase tracking-[0.16em] text-cyan-200"
                                            >
                                                {window}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </article>

                <article className="rounded-[24px] border border-white/8 bg-slate-950/70 p-6">
                    <div className="text-[10px] font-black uppercase tracking-[0.28em] text-cyan-300">
                        Drop Reasons
                    </div>
                    <h3 className="mt-3 text-xl font-black tracking-tight text-white">
                        Why rows are excluded
                    </h3>
                    <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                        Drop reasons stay visible here as monitoring signals, not approval
                        controls for recalibration.
                    </p>

                    {dropEntries.length === 0 ? (
                        <EmptyMiniState text="No dropped rows are currently recorded in the readiness summary." />
                    ) : (
                        <div className="mt-6 space-y-3">
                            {dropEntries.map(([reason, count]) => (
                                <div
                                    key={reason}
                                    className="flex items-start justify-between gap-4 rounded-2xl border border-white/8 bg-white/3 p-4"
                                >
                                    <div>
                                        <div className="text-sm font-semibold text-white">
                                            {reason.replaceAll('_', ' ')}
                                        </div>
                                        <div className="mt-1 text-xs uppercase tracking-[0.18em] text-slate-500">
                                            builder exclusion
                                        </div>
                                    </div>
                                    <div className="text-right">
                                        <div className="text-lg font-black text-amber-200">
                                            {count}
                                        </div>
                                        <div className="text-xs uppercase tracking-[0.18em] text-slate-500">
                                            rows
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </article>
            </section>
        </div>
    );
}

function groupObservationsByDirection(
    observations: NonNullable<TechnicalCalibrationObservationBuildResultModel['observations']>
) {
    const map = new Map<
        string,
        { count: number; totalTargetOutcome: number; windows: Set<string> }
    >();

    for (const observation of observations) {
        const existing = map.get(observation.direction);
        if (existing) {
            existing.count += 1;
            existing.totalTargetOutcome += observation.target_outcome;
            existing.windows.add(`${observation.timeframe}/${observation.horizon}`);
        } else {
            map.set(observation.direction, {
                count: 1,
                totalTargetOutcome: observation.target_outcome,
                windows: new Set([`${observation.timeframe}/${observation.horizon}`]),
            });
        }
    }

    return [...map.entries()].map(([direction, value]) => ({
        direction,
        count: value.count,
        averageTargetOutcome: value.count === 0
            ? 'n/a'
            : `${((value.totalTargetOutcome / value.count) * 100).toFixed(1)}%`,
        windows: [...value.windows].sort(),
    }));
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

function EmptyMiniState({ text }: { text: string }) {
    return (
        <div className="mt-6 rounded-2xl border border-dashed border-white/10 bg-white/3 p-4 text-sm leading-6 text-slate-400">
            {text}
        </div>
    );
}
