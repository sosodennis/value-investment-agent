'use client';

import { useState } from 'react';
import { ExternalLink, FileText, ShieldAlert } from 'lucide-react';

import { useTechnicalObservabilityEventDetail } from '@/hooks/useTechnicalObservability';
import type {
    TechnicalMonitoringRowModel,
    TechnicalObservabilityFilters,
} from '@/types/technical-observability';

type TechnicalObservabilityEventExplorerTabProps = {
    rows: TechnicalMonitoringRowModel[];
    filters: TechnicalObservabilityFilters;
    isLoading: boolean;
    error: Error | null;
};

const BACKEND_URL =
    process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000';

export function TechnicalObservabilityEventExplorerTab({
    rows,
    filters,
    isLoading,
    error,
}: TechnicalObservabilityEventExplorerTabProps) {
    const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
    const selectedRow =
        selectedEventId === null
            ? null
            : rows.find((row) => row.event_id === selectedEventId) ?? null;
    const eventDetailState = useTechnicalObservabilityEventDetail(
        selectedRow?.event_id ?? null,
        filters.labelingMethodVersion
    );

    return (
        <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
            <article className="rounded-[24px] border border-white/8 bg-[linear-gradient(180deg,rgba(15,23,42,0.82),rgba(2,6,23,0.96))] p-6">
                <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
                    <div>
                        <div className="text-[10px] font-black uppercase tracking-[0.28em] text-cyan-300">
                            Investigation Queue
                        </div>
                        <h3 className="mt-3 text-xl font-black tracking-tight text-white">
                            Event Explorer
                        </h3>
                        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                            Review resolved and unresolved prediction events, then open a
                            detail panel with artifact references and raw outcome context.
                        </p>
                    </div>
                    <div className="text-sm text-slate-400">
                        {rows.length} rows in current filter scope
                    </div>
                </div>

                {error ? (
                    <DegradedPanel
                        title="Explorer data is degraded"
                        body={error.message}
                        className="mt-5"
                    />
                ) : null}

                {isLoading && rows.length === 0 ? (
                    <EmptyListState
                        title="Loading event rows"
                        body="Fetching the current investigation queue from the monitoring read model."
                    />
                ) : null}

                {!isLoading && rows.length === 0 ? (
                    <EmptyListState
                        title="No events match the current filters"
                        body="Widen the date scope or clear ticker and direction filters to reopen the investigation queue."
                    />
                ) : null}

                {rows.length > 0 ? (
                    <div className="mt-5 overflow-hidden rounded-[24px] border border-white/8">
                        <div className="grid grid-cols-[1.1fr_0.7fr_0.7fr_0.8fr_0.9fr] gap-3 border-b border-white/8 bg-white/4 px-4 py-3 text-[11px] font-black uppercase tracking-[0.2em] text-slate-500">
                            <div>Event</div>
                            <div>Window</div>
                            <div>Confidence</div>
                            <div>Outcome</div>
                            <div>Status</div>
                        </div>

                        <div className="divide-y divide-white/6">
                            {rows.map((row) => {
                                const isSelected = row.event_id === selectedEventId;
                                return (
                                    <button
                                        key={row.event_id}
                                        type="button"
                                        onClick={() => setSelectedEventId(row.event_id)}
                                        className={`grid w-full cursor-pointer grid-cols-[1.1fr_0.7fr_0.7fr_0.8fr_0.9fr] gap-3 px-4 py-4 text-left transition ${
                                            isSelected
                                                ? 'bg-cyan-500/12'
                                                : 'bg-transparent hover:bg-white/4'
                                        }`}
                                        aria-label={`Inspect ${row.event_id}`}
                                    >
                                        <div>
                                            <div className="text-sm font-black uppercase tracking-[0.18em] text-white">
                                                {row.ticker}
                                            </div>
                                            <div className="mt-1 text-xs uppercase tracking-[0.18em] text-slate-500">
                                                {row.direction} · {formatDateTime(row.event_time)}
                                            </div>
                                        </div>
                                        <CellValue
                                            primary={`${row.timeframe} / ${row.horizon}`}
                                            secondary={row.logic_version}
                                        />
                                        <CellValue
                                            primary={formatOptionalNumber(row.confidence)}
                                            secondary={`score ${formatOptionalNumber(row.raw_score)}`}
                                        />
                                        <CellValue
                                            primary={formatSignedPercent(row.forward_return)}
                                            secondary={`mfe ${formatSignedPercent(row.mfe)}`}
                                        />
                                        <CellValue
                                            primary={
                                                row.resolved_at
                                                    ? 'Resolved'
                                                    : 'Pending outcome'
                                            }
                                            secondary={
                                                row.resolved_at
                                                    ? formatDateTime(row.resolved_at)
                                                    : `${row.data_quality_flags.length} quality flags`
                                            }
                                        />
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                ) : null}
            </article>

            <EventDetailPanel
                selectedRow={selectedRow}
                detail={eventDetailState.detail}
                isLoading={eventDetailState.isLoading}
                error={eventDetailState.error}
            />
        </div>
    );
}

type EventDetailPanelProps = {
    selectedRow: TechnicalMonitoringRowModel | null;
    detail: ReturnType<typeof useTechnicalObservabilityEventDetail>['detail'];
    isLoading: boolean;
    error: Error | null;
};

function EventDetailPanel({
    selectedRow,
    detail,
    isLoading,
    error,
}: EventDetailPanelProps) {
    return (
        <aside className="rounded-[24px] border border-white/8 bg-slate-950/70 p-6">
            <div className="text-[10px] font-black uppercase tracking-[0.28em] text-cyan-300">
                Event Detail
            </div>

            {selectedRow === null ? (
                <div className="mt-5 rounded-2xl border border-dashed border-white/10 bg-white/3 p-5">
                    <h3 className="text-lg font-black tracking-tight text-white">
                        Select an event to investigate
                    </h3>
                    <p className="mt-3 text-sm leading-6 text-slate-400">
                        The drill-down panel will show report artifact links, source
                        artifact references, raw outcome metrics, and data-quality flags.
                    </p>
                </div>
            ) : null}

            {selectedRow !== null && isLoading ? (
                <div className="mt-5 rounded-2xl border border-white/8 bg-white/3 p-5 text-sm leading-6 text-slate-400">
                    Loading event detail for {selectedRow.ticker} / {selectedRow.event_id}.
                </div>
            ) : null}

            {selectedRow !== null && error ? (
                <DegradedPanel
                    title="Event detail failed to load"
                    body={error.message}
                    className="mt-5"
                />
            ) : null}

            {selectedRow !== null && detail !== null && !isLoading && !error ? (
                <div className="mt-5 space-y-5">
                    <div>
                        <h3 className="text-xl font-black tracking-tight text-white">
                            {detail.ticker} · {detail.direction}
                        </h3>
                        <p className="mt-2 text-sm leading-6 text-slate-400">
                            {detail.timeframe} / {detail.horizon} · {detail.logic_version} ·{' '}
                            {formatDateTime(detail.event_time)}
                        </p>
                    </div>

                    <div className="grid gap-4 md:grid-cols-2">
                        <DetailStat
                            label="Forward Return"
                            value={formatSignedPercent(detail.forward_return)}
                        />
                        <DetailStat
                            label="Realized Volatility"
                            value={formatOptionalNumber(detail.realized_volatility)}
                        />
                        <DetailStat
                            label="MFE"
                            value={formatSignedPercent(detail.mfe)}
                        />
                        <DetailStat
                            label="MAE"
                            value={formatSignedPercent(detail.mae)}
                        />
                    </div>

                    <section className="rounded-2xl border border-white/8 bg-white/3 p-4">
                        <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">
                            <FileText className="h-4 w-4 text-cyan-300" />
                            Artifact References
                        </div>
                        <div className="mt-4 space-y-3 text-sm">
                            <ArtifactLinkRow
                                label="Report Artifact"
                                href={buildArtifactHref(detail.full_report_artifact_id)}
                                text={detail.full_report_artifact_id}
                            />
                            {extractArtifactLinks(detail.source_artifact_refs).map((link) => (
                                <ArtifactLinkRow
                                    key={link.label}
                                    label={link.label}
                                    href={link.href}
                                    text={link.text}
                                />
                            ))}
                        </div>
                    </section>

                    <section className="rounded-2xl border border-white/8 bg-white/3 p-4">
                        <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">
                            <ShieldAlert className="h-4 w-4 text-cyan-300" />
                            Data Quality Flags
                        </div>
                        {detail.data_quality_flags.length === 0 ? (
                            <p className="mt-4 text-sm leading-6 text-slate-400">
                                No active quality flags on this event.
                            </p>
                        ) : (
                            <div className="mt-4 flex flex-wrap gap-2">
                                {detail.data_quality_flags.map((flag) => (
                                    <span
                                        key={flag}
                                        className="rounded-full border border-amber-400/20 bg-amber-500/10 px-3 py-1 text-xs font-black uppercase tracking-[0.16em] text-amber-200"
                                    >
                                        {flag}
                                    </span>
                                ))}
                            </div>
                        )}
                    </section>

                    <section className="rounded-2xl border border-white/8 bg-white/3 p-4">
                        <div className="text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">
                            Context Snapshot
                        </div>
                        <div className="mt-4 space-y-3">
                            {summarizeContext(detail.context_payload).map((entry) => (
                                <div
                                    key={entry.label}
                                    className="flex items-start justify-between gap-4 border-b border-white/6 pb-3 last:border-b-0"
                                >
                                    <div className="text-[11px] font-black uppercase tracking-[0.18em] text-slate-500">
                                        {entry.label}
                                    </div>
                                    <div className="max-w-[60%] text-right text-sm leading-6 text-slate-200">
                                        {entry.value}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </section>
                </div>
            ) : null}
        </aside>
    );
}

function DegradedPanel({
    title,
    body,
    className = '',
}: {
    title: string;
    body: string;
    className?: string;
}) {
    return (
        <div
            className={`rounded-2xl border border-amber-400/20 bg-amber-500/10 p-4 text-sm text-amber-50 ${className}`.trim()}
        >
            <div className="text-[10px] font-black uppercase tracking-[0.24em] text-amber-300">
                Degraded State
            </div>
            <div className="mt-2 text-base font-black text-white">{title}</div>
            <p className="mt-2 leading-6 text-amber-100/90">{body}</p>
        </div>
    );
}

function EmptyListState({
    title,
    body,
}: {
    title: string;
    body: string;
}) {
    return (
        <div className="mt-5 rounded-2xl border border-dashed border-white/10 bg-white/3 p-5">
            <h3 className="text-lg font-black tracking-tight text-white">{title}</h3>
            <p className="mt-3 text-sm leading-6 text-slate-400">{body}</p>
        </div>
    );
}

function CellValue({
    primary,
    secondary,
}: {
    primary: string;
    secondary: string;
}) {
    return (
        <div>
            <div className="text-sm font-semibold text-slate-100">{primary}</div>
            <div className="mt-1 text-xs uppercase tracking-[0.16em] text-slate-500">
                {secondary}
            </div>
        </div>
    );
}

function DetailStat({ label, value }: { label: string; value: string }) {
    return (
        <div className="rounded-2xl border border-white/8 bg-white/3 p-4">
            <div className="text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">
                {label}
            </div>
            <div className="mt-3 text-lg font-black tracking-tight text-white">
                {value}
            </div>
        </div>
    );
}

function ArtifactLinkRow({
    label,
    href,
    text,
}: {
    label: string;
    href: string;
    text: string;
}) {
    return (
        <div className="flex items-start justify-between gap-4 border-b border-white/6 pb-3 last:border-b-0">
            <div className="text-[11px] font-black uppercase tracking-[0.18em] text-slate-500">
                {label}
            </div>
            <a
                href={href}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-2 text-right text-sm font-semibold text-cyan-200 transition hover:text-cyan-100"
            >
                <span>{text}</span>
                <ExternalLink className="h-4 w-4" />
            </a>
        </div>
    );
}

function buildArtifactHref(value: string): string {
    if (value.startsWith('http://') || value.startsWith('https://')) {
        return value;
    }
    return `${BACKEND_URL}/api/artifacts/${value}`;
}

function extractArtifactLinks(
    sourceArtifactRefs: Record<string, unknown>
): Array<{ label: string; href: string; text: string }> {
    return Object.entries(sourceArtifactRefs)
        .filter((entry): entry is [string, string] => typeof entry[1] === 'string')
        .map(([label, value]) => ({
            label: label.replaceAll('_', ' '),
            href: buildArtifactHref(value),
            text: value,
        }));
}

function summarizeContext(
    contextPayload: Record<string, unknown>
): Array<{ label: string; value: string }> {
    const entries = Object.entries(contextPayload).slice(0, 8);
    if (entries.length === 0) {
        return [{ label: 'Context', value: 'No compact context payload was recorded.' }];
    }

    return entries.map(([label, value]) => ({
        label: label.replaceAll('_', ' '),
        value: serializeContextValue(value),
    }));
}

function serializeContextValue(value: unknown): string {
    if (value === null) {
        return 'null';
    }
    if (
        typeof value === 'string' ||
        typeof value === 'number' ||
        typeof value === 'boolean'
    ) {
        return String(value);
    }
    if (Array.isArray(value)) {
        return value.map((entry) => serializeContextValue(entry)).join(', ');
    }
    return JSON.stringify(value);
}

function formatOptionalNumber(value: number | null | undefined): string {
    if (value === null || value === undefined) {
        return 'n/a';
    }
    return value.toFixed(2);
}

function formatSignedPercent(value: number | null | undefined): string {
    if (value === null || value === undefined) {
        return 'n/a';
    }
    const percentage = value * 100;
    const prefix = percentage > 0 ? '+' : '';
    return `${prefix}${percentage.toFixed(2)}%`;
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
