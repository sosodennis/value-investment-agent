'use client';

import { startTransition, useState } from 'react';
import Link from 'next/link';
import { Activity, Database } from 'lucide-react';

import { PrimaryViewNav } from '@/components/PrimaryViewNav';
import {
    createDefaultTechnicalObservabilityFilters,
    TECHNICAL_OBSERVABILITY_VIEWS,
    TechnicalObservabilityFilters,
    TechnicalObservabilityView,
} from '@/types/technical-observability';
import { useTechnicalObservability } from '@/hooks/useTechnicalObservability';

import { ObservabilityFilterBar } from './ObservabilityFilterBar';
import {
    TechnicalObservabilityCohortTab,
    type TechnicalObservabilityLabelLens,
} from './TechnicalObservabilityCohortTab';
import { TechnicalObservabilityEventExplorerTab } from './TechnicalObservabilityEventExplorerTab';
import { TechnicalObservabilityCalibrationTab } from './TechnicalObservabilityCalibrationTab';
import { TechnicalObservabilityOverviewTab } from './TechnicalObservabilityOverviewTab';

const VIEW_COPY: Record<
    TechnicalObservabilityView,
    { title: string; kicker: string; description: string }
> = {
    overview: {
        title: 'Overview',
        kicker: 'Monitoring Truth',
        description:
            'Track event volume, labeling coverage, unresolved backlog, and truth-model quality signals before drilling into individual decisions.',
    },
    events: {
        title: 'Event Explorer',
        kicker: 'Investigation Workspace',
        description:
            'Inspect event rows, open detail drill-down, and jump back to source artifacts or report references from the DB-backed read model.',
    },
    cohorts: {
        title: 'Cohort Analysis',
        kicker: 'Grouped Behavior',
        description:
            'Inspect grouped behavior across timeframe, horizon, and logic-version slices while keeping raw truth distinct from governed label snapshots.',
    },
    calibration: {
        title: 'Calibration Readiness',
        kicker: 'Sample Sufficiency',
        description:
            'Monitor usable sample depth and drop reasons without turning this UI into a recalibration control surface.',
    },
};

export function TechnicalObservabilityWorkspace() {
    const [activeView, setActiveView] =
        useState<TechnicalObservabilityView>('overview');
    const [draftFilters, setDraftFilters] = useState<TechnicalObservabilityFilters>(
        () => createDefaultTechnicalObservabilityFilters()
    );
    const [appliedFilters, setAppliedFilters] =
        useState<TechnicalObservabilityFilters>(draftFilters);
    const [isApplying, setIsApplying] = useState(false);
    const [labelLens, setLabelLens] =
        useState<TechnicalObservabilityLabelLens>('raw_outcomes');

    const { aggregates, rows, calibrationReadiness, isLoading, error } =
        useTechnicalObservability(appliedFilters);

    const handleApply = () => {
        setIsApplying(true);
        startTransition(() => {
            setAppliedFilters(draftFilters);
            setIsApplying(false);
        });
    };

    const handleReset = () => {
        const nextFilters = createDefaultTechnicalObservabilityFilters();
        setDraftFilters(nextFilters);
        setAppliedFilters(nextFilters);
    };

    const activeViewCopy = VIEW_COPY[activeView];
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

    return (
        <main className="min-h-screen bg-[radial-gradient(circle_at_top,rgba(8,145,178,0.16),transparent_28%),linear-gradient(180deg,#020617_0%,#020617_44%,#030712_100%)] text-white selection:bg-cyan-500/30">
            <header className="border-b border-white/6 bg-slate-950/70 px-6 py-5 backdrop-blur xl:px-8">
                <div className="mx-auto flex max-w-[1600px] flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                    <div className="flex items-center gap-6">
                        <div>
                            <div className="text-[10px] font-black uppercase tracking-[0.28em] text-cyan-300">
                                Internal Governance
                            </div>
                            <h1 className="mt-2 text-2xl font-black tracking-tight text-white">
                                Technical Observability
                            </h1>
                        </div>
                        <PrimaryViewNav currentView="technical-observability" />
                    </div>

                    <div className="flex flex-wrap items-center gap-3">
                        <StatusPill icon={Database} label="DB Truth Model" />
                        <StatusPill
                            icon={Activity}
                            label={isLoading ? 'Refreshing' : 'Read Model Ready'}
                        />
                        <Link
                            href="/"
                            className="min-h-11 rounded-xl border border-white/10 px-4 py-2.5 text-[11px] font-black uppercase tracking-[0.2em] text-slate-300 transition hover:border-white/20 hover:text-white"
                        >
                            Back To Analysis
                        </Link>
                    </div>
                </div>
            </header>

            <div className="mx-auto flex max-w-[1600px] flex-col gap-6 px-6 py-8 xl:px-8">
                <ObservabilityFilterBar
                    draftFilters={draftFilters}
                    isApplying={isApplying}
                    onDraftFiltersChange={setDraftFilters}
                    onApply={handleApply}
                    onReset={handleReset}
                />

                <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                    <MetricCard
                        label="Total Events"
                        value={String(totalEvents)}
                        helper="Prediction events inside the current shared filter scope."
                    />
                    <MetricCard
                        label="Label Coverage"
                        value={labelCoverage}
                        helper={`${totalLabeled} labeled events currently attached to raw outcomes.`}
                    />
                    <MetricCard
                        label="Unresolved Backlog"
                        value={String(totalUnresolved)}
                        helper="Events still waiting for their horizon to mature."
                    />
                    <MetricCard
                        label="Quality Flagged Rows"
                        value={String(qualityFlaggedRows)}
                        helper="Rows currently carrying data-quality annotations."
                    />
                </section>

                <section className="rounded-[28px] border border-white/8 bg-slate-950/60 p-5 shadow-[0_22px_70px_rgba(2,6,23,0.32)]">
                    <div className="flex flex-wrap gap-2">
                        {TECHNICAL_OBSERVABILITY_VIEWS.map((view) => {
                            const isActive = view === activeView;
                            return (
                                <button
                                    key={view}
                                    type="button"
                                    onClick={() => setActiveView(view)}
                                    className={`min-h-11 rounded-xl px-4 text-xs font-black uppercase tracking-[0.22em] transition ${
                                        isActive
                                            ? 'bg-cyan-500/14 text-cyan-200 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.25)]'
                                            : 'text-slate-400 hover:bg-white/4 hover:text-white'
                                    }`}
                                >
                                    {VIEW_COPY[view].title}
                                </button>
                            );
                        })}
                    </div>

                    <div className="mt-6">
                        <article className="rounded-[24px] border border-white/8 bg-[linear-gradient(180deg,rgba(15,23,42,0.82),rgba(2,6,23,0.96))] p-6">
                            <div className="text-[10px] font-black uppercase tracking-[0.28em] text-cyan-300">
                                {activeViewCopy.kicker}
                            </div>
                            <h2 className="mt-3 text-2xl font-black tracking-tight text-white">
                                {activeViewCopy.title}
                            </h2>
                            <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">
                                {activeViewCopy.description}
                            </p>
                        </article>

                        <div className="mt-6">
                            {activeView === 'overview' ? (
                                <TechnicalObservabilityOverviewTab
                                    filters={appliedFilters}
                                    aggregates={aggregates}
                                    rows={rows}
                                    calibrationReadiness={calibrationReadiness}
                                    isLoading={isLoading}
                                    error={error}
                                />
                            ) : null}
                            {activeView === 'events' ? (
                                <TechnicalObservabilityEventExplorerTab
                                    rows={rows}
                                    filters={appliedFilters}
                                    isLoading={isLoading}
                                    error={error}
                                />
                            ) : null}
                            {activeView === 'cohorts' || activeView === 'calibration' ? (
                                <div className="grid gap-6">
                                    <LabelLensControls
                                        labelLens={labelLens}
                                        onChange={setLabelLens}
                                    />
                                    {activeView === 'cohorts' ? (
                                        <TechnicalObservabilityCohortTab
                                            aggregates={aggregates}
                                            isLoading={isLoading}
                                            error={error}
                                            labelLens={labelLens}
                                        />
                                    ) : null}
                                    {activeView === 'calibration' ? (
                                        <TechnicalObservabilityCalibrationTab
                                            calibrationReadiness={calibrationReadiness}
                                            isLoading={isLoading}
                                            error={error}
                                            labelLens={labelLens}
                                        />
                                    ) : null}
                                </div>
                            ) : null}
                            {activeView !== 'overview' &&
                            activeView !== 'events' &&
                            activeView !== 'cohorts' &&
                            activeView !== 'calibration' ? (
                                <PlaceholderView
                                    activeViewTitle={activeViewCopy.title}
                                    description={activeViewCopy.description}
                                    appliedFilters={appliedFilters}
                                    isApplying={isApplying}
                                    isLoading={isLoading}
                                    topDropReason={topDropReason(calibrationReadiness)}
                                />
                            ) : null}
                        </div>
                    </div>
                </section>
            </div>
        </main>
    );
}

type MetricCardProps = {
    label: string;
    value: string;
    helper: string;
};

function MetricCard({ label, value, helper }: MetricCardProps) {
    return (
        <article className="rounded-[24px] border border-white/8 bg-slate-950/60 p-5 shadow-[0_18px_48px_rgba(2,6,23,0.24)]">
            <div>
                <div className="text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">
                    {label}
                </div>
                <div className="mt-4 text-3xl font-black tracking-tight text-white">
                    {value}
                </div>
            </div>
            <p className="mt-4 text-sm leading-6 text-slate-400">{helper}</p>
        </article>
    );
}

type StatusPillProps = {
    icon: React.ComponentType<{ className?: string }>;
    label: string;
};

function StatusPill({ icon: Icon, label }: StatusPillProps) {
    return (
        <div className="flex min-h-11 items-center gap-2 rounded-xl border border-white/10 bg-slate-950/70 px-4 py-2.5 text-[11px] font-black uppercase tracking-[0.2em] text-slate-300">
            <Icon className="h-4 w-4 text-cyan-300" />
            {label}
        </div>
    );
}

type SummaryPanelProps = {
    title: string;
    value: string;
};

function SummaryPanel({ title, value }: SummaryPanelProps) {
    return (
        <div className="rounded-2xl border border-white/8 bg-white/3 p-4">
            <div className="text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">
                {title}
            </div>
            <div className="mt-3 text-sm font-semibold text-slate-100">{value}</div>
        </div>
    );
}

type DetailLineProps = {
    label: string;
    value: string;
};

function DetailLine({ label, value }: DetailLineProps) {
    return (
        <div className="flex items-start justify-between gap-4 border-b border-white/6 pb-3 last:border-b-0">
            <dt className="text-[11px] font-black uppercase tracking-[0.2em] text-slate-500">
                {label}
            </dt>
            <dd className="text-right text-sm font-semibold text-slate-100">
                {value}
            </dd>
        </div>
    );
}

type PlaceholderViewProps = {
    activeViewTitle: string;
    description: string;
    appliedFilters: TechnicalObservabilityFilters;
    isApplying: boolean;
    isLoading: boolean;
    topDropReason: string;
};

type LabelLensControlsProps = {
    labelLens: TechnicalObservabilityLabelLens;
    onChange: (next: TechnicalObservabilityLabelLens) => void;
};

function LabelLensControls({ labelLens, onChange }: LabelLensControlsProps) {
    return (
        <section className="rounded-[24px] border border-white/8 bg-slate-950/70 p-5">
            <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.28em] text-cyan-300">
                        Label Lens
                    </div>
                    <h3 className="mt-3 text-xl font-black tracking-tight text-white">
                        Raw truth and governed labels stay separate
                    </h3>
                    <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">
                        `Raw outcomes` show truth-model monitoring. `Approved snapshots`
                        represent versioned governance labels and must not be mistaken for
                        the same metric surface.
                    </p>
                </div>

                <div className="flex flex-wrap gap-2">
                    <LensButton
                        label="Raw Outcomes"
                        isActive={labelLens === 'raw_outcomes'}
                        onClick={() => onChange('raw_outcomes')}
                    />
                    <LensButton
                        label="Approved Snapshots"
                        isActive={labelLens === 'approved_snapshots'}
                        onClick={() => onChange('approved_snapshots')}
                    />
                </div>
            </div>
        </section>
    );
}

function LensButton({
    label,
    isActive,
    onClick,
}: {
    label: string;
    isActive: boolean;
    onClick: () => void;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            className={`min-h-11 rounded-xl px-4 text-xs font-black uppercase tracking-[0.22em] transition ${
                isActive
                    ? 'bg-cyan-500/14 text-cyan-200 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.25)]'
                    : 'border border-white/10 text-slate-400 hover:bg-white/4 hover:text-white'
            }`}
        >
            {label}
        </button>
    );
}

function PlaceholderView({
    activeViewTitle,
    description,
    appliedFilters,
    isApplying,
    isLoading,
    topDropReason,
}: PlaceholderViewProps) {
    return (
        <div className="grid gap-6 xl:grid-cols-[1.3fr_0.7fr]">
            <article className="rounded-[24px] border border-white/8 bg-[linear-gradient(180deg,rgba(15,23,42,0.82),rgba(2,6,23,0.96))] p-6">
                <div className="text-[10px] font-black uppercase tracking-[0.28em] text-cyan-300">
                    Next Slice
                </div>
                <h3 className="mt-3 text-2xl font-black tracking-tight text-white">
                    {activeViewTitle}
                </h3>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                    {description}
                </p>

                <div className="mt-6 grid gap-4 md:grid-cols-2">
                    <SummaryPanel
                        title="Applied Tickers"
                        value={
                            appliedFilters.tickers.length > 0
                                ? appliedFilters.tickers.join(', ')
                                : 'All tracked tickers'
                        }
                    />
                    <SummaryPanel
                        title="Date Window"
                        value={appliedFilters.datePreset.replace('_', ' ')}
                    />
                    <SummaryPanel
                        title="Labeling Method"
                        value={appliedFilters.labelingMethodVersion}
                    />
                    <SummaryPanel title="Top Drop Reason" value={topDropReason} />
                </div>
            </article>

            <aside className="rounded-[24px] border border-white/8 bg-slate-950/70 p-6">
                <div className="text-[10px] font-black uppercase tracking-[0.28em] text-slate-500">
                    Shared State Preview
                </div>
                <dl className="mt-4 space-y-4 text-sm">
                    <DetailLine label="Current View" value={activeViewTitle} />
                    <DetailLine
                        label="Pending Apply"
                        value={isApplying ? 'Yes' : 'No'}
                    />
                    <DetailLine label="Rows Loading" value={isLoading ? 'Yes' : 'No'} />
                    <DetailLine
                        label="Result Limit"
                        value={String(appliedFilters.limit)}
                    />
                </dl>
            </aside>
        </div>
    );
}

function topDropReason(
    calibrationReadiness: ReturnType<typeof useTechnicalObservability>['calibrationReadiness']
) {
    if (!calibrationReadiness?.dropped_reasons) {
        return 'No dropped rows';
    }

    const entries = Object.entries(calibrationReadiness.dropped_reasons);
    if (entries.length === 0) {
        return 'No dropped rows';
    }

    entries.sort((left, right) => right[1] - left[1]);
    const [reason, count] = entries[0];
    return `${reason} (${count})`;
}
