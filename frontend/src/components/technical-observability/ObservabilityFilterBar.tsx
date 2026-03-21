'use client';

import type { ChangeEvent } from 'react';

import {
    applyTechnicalObservabilityDatePreset,
    parseFilterListInput,
    parseTechnicalObservabilityDatePreset,
    TechnicalObservabilityDatePreset,
    TechnicalObservabilityFilters,
} from '@/types/technical-observability';

type ObservabilityFilterBarProps = {
    draftFilters: TechnicalObservabilityFilters;
    isApplying: boolean;
    onDraftFiltersChange: (next: TechnicalObservabilityFilters) => void;
    onApply: () => void;
    onReset: () => void;
};

const TIMEFRAME_OPTIONS = [
    { label: 'All Timeframes', value: '' },
    { label: '1D', value: '1d' },
    { label: '1W', value: '1wk' },
    { label: '1M', value: '1mo' },
];

const HORIZON_OPTIONS = [
    { label: 'All Horizons', value: '' },
    { label: '1D', value: '1d' },
    { label: '5D', value: '5d' },
    { label: '20D', value: '20d' },
];

const DIRECTION_OPTIONS = [
    { label: 'All Directions', value: '' },
    { label: 'Bullish', value: 'bullish' },
    { label: 'Bearish', value: 'bearish' },
];

const DATE_PRESET_OPTIONS: Array<{
    label: string;
    value: TechnicalObservabilityDatePreset;
}> = [
    { label: 'Last 7D', value: 'last_7d' },
    { label: 'Last 30D', value: 'last_30d' },
    { label: 'Last 90D', value: 'last_90d' },
    { label: 'All Time', value: 'all_time' },
];

const LIMIT_OPTIONS = [
    { label: '50 Rows', value: 50 },
    { label: '200 Rows', value: 200 },
    { label: '500 Rows', value: 500 },
];

export function ObservabilityFilterBar({
    draftFilters,
    isApplying,
    onDraftFiltersChange,
    onApply,
    onReset,
}: ObservabilityFilterBarProps) {
    const updateCsvFilter =
        (field: 'tickers' | 'logicVersions') =>
        (event: ChangeEvent<HTMLInputElement>) => {
            onDraftFiltersChange({
                ...draftFilters,
                [field]: parseFilterListInput(event.target.value),
            });
        };

    const updateSingleSelect =
        (field: 'timeframes' | 'horizons' | 'directions') =>
        (event: ChangeEvent<HTMLSelectElement>) => {
            const value = event.target.value;
            onDraftFiltersChange({
                ...draftFilters,
                [field]: value ? [value] : [],
            });
        };

    const updateDatePreset = (event: ChangeEvent<HTMLSelectElement>) => {
        const datePreset = parseTechnicalObservabilityDatePreset(
            event.target.value
        );
        onDraftFiltersChange({
            ...draftFilters,
            ...applyTechnicalObservabilityDatePreset(datePreset),
        });
    };

    const updateLabelingMethodVersion = (event: ChangeEvent<HTMLInputElement>) => {
        onDraftFiltersChange({
            ...draftFilters,
            labelingMethodVersion: event.target.value,
        });
    };

    const updateLimit = (event: ChangeEvent<HTMLSelectElement>) => {
        onDraftFiltersChange({
            ...draftFilters,
            limit: Number(event.target.value),
        });
    };

    return (
        <section className="rounded-[28px] border border-white/8 bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.12),transparent_42%),linear-gradient(180deg,rgba(15,23,42,0.92),rgba(2,6,23,0.98))] p-6 shadow-[0_30px_80px_rgba(2,6,23,0.36)]">
            <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
                <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.28em] text-cyan-300">
                        Shared Filters
                    </div>
                    <h2 className="mt-2 text-xl font-black tracking-tight text-white">
                        Technical Observability Workspace
                    </h2>
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
                        Scope aggregates, event rows, and calibration readiness from the
                        same DB truth model before deeper views land.
                    </p>
                </div>

                <div className="flex items-center gap-3">
                    <button
                        type="button"
                        onClick={onReset}
                        className="min-h-11 rounded-xl border border-white/10 px-4 text-xs font-bold uppercase tracking-[0.2em] text-slate-300 transition hover:border-white/20 hover:text-white"
                    >
                        Reset
                    </button>
                    <button
                        type="button"
                        onClick={onApply}
                        disabled={isApplying}
                        className="min-h-11 rounded-xl bg-gradient-to-r from-cyan-500 to-teal-500 px-5 text-xs font-black uppercase tracking-[0.24em] text-slate-950 shadow-[0_14px_40px_rgba(20,184,166,0.35)] transition hover:opacity-90 disabled:opacity-60"
                    >
                        {isApplying ? 'Applying' : 'Apply Filters'}
                    </button>
                </div>
            </div>

            <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                <FilterField label="Tickers">
                    <input
                        aria-label="Tickers"
                        className="min-h-11 w-full rounded-xl border border-white/8 bg-slate-950/70 px-4 text-sm text-white outline-none transition focus:border-cyan-400/60"
                        placeholder="AAPL, MSFT"
                        value={draftFilters.tickers.join(', ')}
                        onChange={updateCsvFilter('tickers')}
                    />
                </FilterField>

                <FilterField label="Timeframe">
                    <select
                        aria-label="Timeframe"
                        className="min-h-11 w-full rounded-xl border border-white/8 bg-slate-950/70 px-4 text-sm text-white outline-none transition focus:border-cyan-400/60"
                        value={draftFilters.timeframes[0] ?? ''}
                        onChange={updateSingleSelect('timeframes')}
                    >
                        {TIMEFRAME_OPTIONS.map((option) => (
                            <option key={option.label} value={option.value}>
                                {option.label}
                            </option>
                        ))}
                    </select>
                </FilterField>

                <FilterField label="Horizon">
                    <select
                        aria-label="Horizon"
                        className="min-h-11 w-full rounded-xl border border-white/8 bg-slate-950/70 px-4 text-sm text-white outline-none transition focus:border-cyan-400/60"
                        value={draftFilters.horizons[0] ?? ''}
                        onChange={updateSingleSelect('horizons')}
                    >
                        {HORIZON_OPTIONS.map((option) => (
                            <option key={option.label} value={option.value}>
                                {option.label}
                            </option>
                        ))}
                    </select>
                </FilterField>

                <FilterField label="Direction">
                    <select
                        aria-label="Direction"
                        className="min-h-11 w-full rounded-xl border border-white/8 bg-slate-950/70 px-4 text-sm text-white outline-none transition focus:border-cyan-400/60"
                        value={draftFilters.directions[0] ?? ''}
                        onChange={updateSingleSelect('directions')}
                    >
                        {DIRECTION_OPTIONS.map((option) => (
                            <option key={option.label} value={option.value}>
                                {option.label}
                            </option>
                        ))}
                    </select>
                </FilterField>

                <FilterField label="Date Window">
                    <select
                        aria-label="Date Window"
                        className="min-h-11 w-full rounded-xl border border-white/8 bg-slate-950/70 px-4 text-sm text-white outline-none transition focus:border-cyan-400/60"
                        value={draftFilters.datePreset}
                        onChange={updateDatePreset}
                    >
                        {DATE_PRESET_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                                {option.label}
                            </option>
                        ))}
                    </select>
                </FilterField>

                <FilterField label="Labeling Method">
                    <div className="flex items-center gap-3">
                        <input
                            aria-label="Labeling Method"
                            className="min-h-11 w-full rounded-xl border border-white/8 bg-slate-950/70 px-4 text-sm text-white outline-none transition focus:border-cyan-400/60"
                            value={draftFilters.labelingMethodVersion}
                            onChange={updateLabelingMethodVersion}
                        />
                        <select
                            aria-label="Row Limit"
                            className="min-h-11 rounded-xl border border-white/8 bg-slate-950/70 px-4 text-sm text-white outline-none transition focus:border-cyan-400/60"
                            value={draftFilters.limit}
                            onChange={updateLimit}
                        >
                            {LIMIT_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                    </div>
                </FilterField>
            </div>
        </section>
    );
}

type FilterFieldProps = {
    label: string;
    children: React.ReactNode;
};

function FilterField({ label, children }: FilterFieldProps) {
    return (
        <label className="flex flex-col gap-2">
            <span className="text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">
                {label}
            </span>
            {children}
        </label>
    );
}
