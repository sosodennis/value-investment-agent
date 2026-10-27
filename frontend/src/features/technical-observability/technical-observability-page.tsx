'use client';

import { useState, type ReactNode } from 'react';
import Link from 'next/link';
import { ExternalLink, RefreshCw } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table';
import {
    useTechnicalObservability,
    useTechnicalObservabilityEventDetail,
} from '@/hooks/useTechnicalObservability';
import {
    applyTechnicalObservabilityDatePreset,
    createDefaultTechnicalObservabilityFilters,
    parseFilterListInput,
    parseTechnicalObservabilityDatePreset,
    type TechnicalObservabilityDatePreset,
    type TechnicalObservabilityView,
} from '@/types/technical-observability';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import { buildArtifactUrl } from '@/features/artifacts/api';

const VIEWS: { id: TechnicalObservabilityView; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'events', label: 'Events' },
    { id: 'cohorts', label: 'Cohorts' },
    { id: 'calibration', label: 'Calibration' },
];

const TIMEFRAMES = [
    { value: '1d', label: '1D' },
    { value: '1wk', label: '1W' },
    { value: '1mo', label: '1M' },
];
const HORIZONS = [
    { value: '1d', label: '1D' },
    { value: '5d', label: '5D' },
    { value: '20d', label: '20D' },
];
const DIRECTIONS = [
    { value: 'bullish', label: 'Bullish' },
    { value: 'bearish', label: 'Bearish' },
];
const DATE_PRESETS: { value: TechnicalObservabilityDatePreset; label: string }[] = [
    { value: 'last_7d', label: 'Last 7 days' },
    { value: 'last_30d', label: 'Last 30 days' },
    { value: 'last_90d', label: 'Last 90 days' },
    { value: 'all_time', label: 'All time' },
];
const LIMITS = [50, 200, 500];
type LabelLens = 'raw_outcomes' | 'approved_snapshots';

function isTechnicalObservabilityView(
    value: string
): value is TechnicalObservabilityView {
    return VIEWS.some((view) => view.id === value);
}

export function TechnicalObservabilityPage() {
    const defaults = createDefaultTechnicalObservabilityFilters();
    const [draft, setDraft] = useState(defaults);
    const [filters, setFilters] = useState(defaults);
    const [view, setView] = useState<TechnicalObservabilityView>('overview');
    const [labelLens, setLabelLens] = useState<LabelLens>('raw_outcomes');
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const data = useTechnicalObservability(filters);
    const detail = useTechnicalObservabilityEventDetail(
        selectedId,
        filters.labelingMethodVersion
    );

    const activeCount = data.aggregates.reduce((sum, row) => sum + row.event_count, 0);
    const labeledCount = data.aggregates.reduce((sum, row) => sum + row.labeled_event_count, 0);
    const unresolvedCount = data.aggregates.reduce(
        (sum, row) => sum + row.unresolved_event_count,
        0
    );

    return (
        <main className="mx-auto flex w-full max-w-[1600px] flex-col gap-5 px-4 py-6 sm:px-6">
            <header className="flex flex-wrap items-center justify-between gap-4 border-b pb-4">
                <div>
                    <p className="text-sm text-muted-foreground">
                        Monitoring / Technical
                    </p>
                    <h1 className="mt-1 text-2xl font-semibold">
                        Technical Observability
                    </h1>
                </div>
                <div className="flex items-center gap-3">
                    <Badge variant="outline">Read model</Badge>
                    <Link
                        className="text-sm text-primary underline-offset-4 hover:underline"
                        href="/workspace"
                    >
                        Workspace
                    </Link>
                </div>
            </header>

            <form
                className="grid gap-4 rounded-md border bg-card p-4 sm:grid-cols-2 xl:grid-cols-4"
                onSubmit={(event) => {
                    event.preventDefault();
                    setFilters(draft);
                }}
            >
                <ListFilter
                    label="Tickers"
                    id="obs-tickers"
                    value={draft.tickers}
                    placeholder="AAPL, MSFT"
                    onChange={(tickers) =>
                        setDraft((current) => ({ ...current, tickers }))
                    }
                />
                <ListFilter
                    label="Agent sources"
                    id="obs-agent-sources"
                    value={draft.agentSources}
                    placeholder="technical_analysis"
                    onChange={(agentSources) =>
                        setDraft((current) => ({ ...current, agentSources }))
                    }
                />
                <SelectFilter
                    label="Timeframe"
                    id="obs-timeframe"
                    value={draft.timeframes[0] ?? ''}
                    options={TIMEFRAMES}
                    onChange={(value) =>
                        setDraft((current) => ({
                            ...current,
                            timeframes: value ? [value] : [],
                        }))
                    }
                />
                <SelectFilter
                    label="Horizon"
                    id="obs-horizon"
                    value={draft.horizons[0] ?? ''}
                    options={HORIZONS}
                    onChange={(value) =>
                        setDraft((current) => ({
                            ...current,
                            horizons: value ? [value] : [],
                        }))
                    }
                />
                <ListFilter
                    label="Logic versions"
                    id="obs-logic-versions"
                    value={draft.logicVersions}
                    placeholder="v1, v2"
                    onChange={(logicVersions) =>
                        setDraft((current) => ({ ...current, logicVersions }))
                    }
                />
                <SelectFilter
                    label="Direction"
                    id="obs-direction"
                    value={draft.directions[0] ?? ''}
                    options={DIRECTIONS}
                    onChange={(value) =>
                        setDraft((current) => ({
                            ...current,
                            directions: value ? [value] : [],
                        }))
                    }
                />
                <ListFilter
                    label="Run types"
                    id="obs-run-types"
                    value={draft.runTypes}
                    placeholder="workflow"
                    onChange={(runTypes) =>
                        setDraft((current) => ({ ...current, runTypes }))
                    }
                />
                <ListFilter
                    label="Reliability levels"
                    id="obs-reliability"
                    value={draft.reliabilityLevels}
                    placeholder="high, medium"
                    onChange={(reliabilityLevels) =>
                        setDraft((current) => ({ ...current, reliabilityLevels }))
                    }
                />
                <SelectFilter
                    label="Date window"
                    id="obs-date-preset"
                    value={draft.datePreset}
                    options={DATE_PRESETS}
                    onChange={(value) =>
                        setDraft((current) => ({
                            ...current,
                            ...applyTechnicalObservabilityDatePreset(
                                parseTechnicalObservabilityDatePreset(value)
                            ),
                        }))
                    }
                />
                <DateFilter
                    label="Event start"
                    id="obs-event-start"
                    value={draft.eventTimeStart}
                    onChange={(eventTimeStart) =>
                        setDraft((current) => ({
                            ...current,
                            eventTimeStart,
                            datePreset: 'all_time',
                        }))
                    }
                />
                <DateFilter
                    label="Event end"
                    id="obs-event-end"
                    value={draft.eventTimeEnd}
                    onChange={(eventTimeEnd) =>
                        setDraft((current) => ({
                            ...current,
                            eventTimeEnd,
                            datePreset: 'all_time',
                        }))
                    }
                    endOfDay
                />
                <DateFilter
                    label="Resolved start"
                    id="obs-resolved-start"
                    value={draft.resolvedTimeStart}
                    onChange={(resolvedTimeStart) =>
                        setDraft((current) => ({ ...current, resolvedTimeStart }))
                    }
                />
                <DateFilter
                    label="Resolved end"
                    id="obs-resolved-end"
                    value={draft.resolvedTimeEnd}
                    onChange={(resolvedTimeEnd) =>
                        setDraft((current) => ({ ...current, resolvedTimeEnd }))
                    }
                    endOfDay
                />
                <Field label="Labeling method" htmlFor="obs-labeling">
                    <Input
                        id="obs-labeling"
                        value={draft.labelingMethodVersion}
                        onChange={(event) =>
                            setDraft((current) => ({
                                ...current,
                                labelingMethodVersion: event.target.value,
                            }))
                        }
                    />
                </Field>
                <SelectFilter
                    label="Row limit"
                    id="obs-limit"
                    value={String(draft.limit)}
                    options={LIMITS.map((limit) => ({
                        value: String(limit),
                        label: `${limit} rows`,
                    }))}
                    onChange={(value) =>
                        setDraft((current) => ({ ...current, limit: Number(value) }))
                    }
                />
                <div className="flex items-end gap-2 md:col-span-2 xl:col-span-4">
                    <Button type="submit">
                        <RefreshCw aria-hidden="true" />
                        Apply filters
                    </Button>
                    <Button
                        type="button"
                        variant="outline"
                        onClick={() => {
                            const next = createDefaultTechnicalObservabilityFilters();
                            setDraft(next);
                            setFilters(next);
                        }}
                    >
                        Reset
                    </Button>
                    <span className="ml-auto text-sm text-muted-foreground">
                        {data.isLoading
                            ? 'Refreshing data…'
                            : `${activeCount} events in scope`}
                    </span>
                </div>
            </form>

            <section aria-label="Monitoring summary" className="grid gap-3 sm:grid-cols-3">
                <Metric
                    label="Events"
                    value={activeCount}
                    loading={data.aggregatesLoading}
                    error={data.aggregatesError}
                />
                <Metric
                    label="Labeled"
                    value={labeledCount}
                    loading={data.aggregatesLoading}
                    error={data.aggregatesError}
                />
                <Metric
                    label="Unresolved"
                    value={unresolvedCount}
                    loading={data.aggregatesLoading}
                    error={data.aggregatesError}
                />
            </section>

            <Tabs
                value={view}
                onValueChange={(value) => {
                    if (isTechnicalObservabilityView(value)) {
                        setView(value);
                    }
                }}
            >
                <TabsList aria-label="Observability views" className="w-full justify-start overflow-x-auto">
                    {VIEWS.map((item) => <TabsTrigger key={item.id} value={item.id}>{item.label}</TabsTrigger>)}
                </TabsList>
                {VIEWS.map((item) => (
                    <TabsContent key={item.id} value={item.id}>
                        {item.id === 'overview' && (
                            <div className="grid gap-4 xl:grid-cols-2">
                                <AggregateOverview data={data} />
                                <QualityOverview data={data} />
                            </div>
                        )}
                        {item.id === 'events' && (
                            <EventExplorer
                                rows={data.rows}
                                loading={data.rowsLoading}
                                validating={data.rowsValidating}
                                error={data.rowsError}
                                retryRows={data.retryRows}
                                selectedId={selectedId}
                                onSelect={setSelectedId}
                                detail={detail}
                            />
                        )}
                        {item.id === 'cohorts' && (
                            <CohortsView data={data} labelLens={labelLens} onLensChange={setLabelLens} />
                        )}
                        {item.id === 'calibration' && (
                            <CalibrationView data={data} labelLens={labelLens} onLensChange={setLabelLens} />
                        )}
                    </TabsContent>
                ))}
            </Tabs>
        </main>
    );
}

type ObservabilityData = ReturnType<typeof useTechnicalObservability>;

function AggregateOverview({ data }: { data: ObservabilityData }) {
    return (
        <DataState
            title="Event volume by cohort"
            loading={data.aggregatesLoading}
            validating={data.aggregatesValidating}
            retry={data.retryAggregates}
            error={data.aggregatesError}
            empty={data.aggregates.length === 0}
        >
            <div className="overflow-x-auto">
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>Timeframe</TableHead>
                            <TableHead>Horizon</TableHead>
                            <TableHead>Logic</TableHead>
                            <TableHead>Events</TableHead>
                            <TableHead>Labeled</TableHead>
                            <TableHead>Unresolved</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {data.aggregates.map((row) => (
                            <TableRow
                                key={`${row.timeframe}-${row.horizon}-${row.logic_version}`}
                            >
                                <TableCell>{row.timeframe}</TableCell>
                                <TableCell>{row.horizon}</TableCell>
                                <TableCell>{row.logic_version}</TableCell>
                                <TableCell>{row.event_count}</TableCell>
                                <TableCell>{row.labeled_event_count}</TableCell>
                                <TableCell>{row.unresolved_event_count}</TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
        </DataState>
    );
}

function QualityOverview({ data }: { data: ObservabilityData }) {
    const flaggedRows = data.rows.filter((row) => row.data_quality_flags.length > 0);
    const flags = [...new Set(data.rows.flatMap((row) => row.data_quality_flags))];

    return (
        <DataState
            title="Data quality"
            loading={data.rowsLoading}
            validating={data.rowsValidating}
            retry={data.retryRows}
            error={data.rowsError}
            empty={data.rows.length === 0}
        >
            <p className="text-sm text-muted-foreground">
                {flaggedRows.length} of {data.rows.length} returned rows have quality
                flags.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
                {flags.map((flag) => (
                    <Badge key={flag} variant="secondary">
                        {flag}
                    </Badge>
                ))}
            </div>
        </DataState>
    );
}

function CohortsView({
    data,
    labelLens,
    onLensChange,
}: {
    data: ObservabilityData;
    labelLens: LabelLens;
    onLensChange: (value: LabelLens) => void;
}) {
    return (
        <div className="grid gap-4">
            <LabelLensControl value={labelLens} onChange={onLensChange} />
            {labelLens === 'approved_snapshots' ? (
                <ApprovedSnapshotsState />
            ) : (
                <DataState
                    title="Raw outcome cohorts"
                    loading={data.aggregatesLoading}
                    validating={data.aggregatesValidating}
                    retry={data.retryAggregates}
                    error={data.aggregatesError}
                    empty={data.aggregates.length === 0}
                >
                    <div className="overflow-x-auto">
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Timeframe</TableHead>
                                    <TableHead>Horizon</TableHead>
                                    <TableHead>Logic version</TableHead>
                                    <TableHead>Samples</TableHead>
                                    <TableHead>Labeled</TableHead>
                                    <TableHead>Unresolved</TableHead>
                                    <TableHead>Avg confidence</TableHead>
                                    <TableHead>Avg raw score</TableHead>
                                    <TableHead>Avg forward return</TableHead>
                                    <TableHead>Avg realized vol</TableHead>
                                    <TableHead>Avg MFE</TableHead>
                                    <TableHead>Avg MAE</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {data.aggregates.map((row) => (
                                    <TableRow
                                        key={`${row.timeframe}-${row.horizon}-${row.logic_version}`}
                                    >
                                        <TableCell>{row.timeframe}</TableCell>
                                        <TableCell>{row.horizon}</TableCell>
                                        <TableCell>{row.logic_version}</TableCell>
                                        <TableCell>{row.event_count}</TableCell>
                                        <TableCell>{row.labeled_event_count}</TableCell>
                                        <TableCell>{row.unresolved_event_count}</TableCell>
                                        <TableCell>
                                            {formatNumber(row.avg_confidence)}
                                        </TableCell>
                                        <TableCell>{formatMetric(row.avg_raw_score)}</TableCell>
                                        <TableCell>
                                            {formatNumber(row.avg_forward_return)}
                                        </TableCell>
                                        <TableCell>
                                            {formatNumber(row.avg_realized_volatility)}
                                        </TableCell>
                                        <TableCell>{formatNumber(row.avg_mfe)}</TableCell>
                                        <TableCell>{formatNumber(row.avg_mae)}</TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </div>
                </DataState>
            )}
        </div>
    );
}

function CalibrationView({
    data,
    labelLens,
    onLensChange,
}: {
    data: ObservabilityData;
    labelLens: LabelLens;
    onLensChange: (value: LabelLens) => void;
}) {
    const readiness = data.calibrationReadiness;

    return (
        <div className="grid gap-4">
            <LabelLensControl value={labelLens} onChange={onLensChange} />
            {labelLens === 'approved_snapshots' ? (
                <ApprovedSnapshotsState />
            ) : (
                <DataState
                    title="Raw outcome calibration readiness"
                    loading={data.calibrationLoading}
                    validating={data.calibrationValidating}
                    retry={data.retryCalibration}
                    error={data.calibrationError}
                    empty={!readiness}
                >
                    <dl className="grid gap-3 sm:grid-cols-3">
                        <InlineMetric label="Source rows" value={readiness?.row_count ?? 0} />
                        <InlineMetric label="Usable rows" value={readiness?.usable_row_count ?? 0} />
                        <InlineMetric label="Dropped rows" value={readiness?.dropped_row_count ?? 0} />
                    </dl>
                    <ul className="mt-4 flex flex-wrap gap-2">
                        {Object.entries(readiness?.dropped_reasons ?? {}).map(
                            ([reason, count]) => (
                                <li key={reason}>
                                    <Badge variant="outline">
                                        {reason.replaceAll('_', ' ')}: {count}
                                    </Badge>
                                </li>
                            )
                        )}
                    </ul>
                    {readiness?.observations && (
                        <div className="mt-4 overflow-x-auto">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Direction</TableHead>
                                        <TableHead>Timeframe</TableHead>
                                        <TableHead>Horizon</TableHead>
                                        <TableHead>Raw score</TableHead>
                                        <TableHead>Target outcome</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {readiness.observations.map((observation, index) => (
                                        <TableRow
                                            key={`${observation.direction}-${observation.timeframe}-${observation.horizon}-${index}`}
                                        >
                                            <TableCell>{observation.direction}</TableCell>
                                            <TableCell>{observation.timeframe}</TableCell>
                                            <TableCell>{observation.horizon}</TableCell>
                                            <TableCell>
                                                {formatMetric(observation.raw_score)}
                                            </TableCell>
                                            <TableCell>
                                                {formatNumber(observation.target_outcome)}
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>
                    )}
                </DataState>
            )}
        </div>
    );
}

function ListFilter({
    label,
    id,
    value,
    placeholder,
    onChange,
}: {
    label: string;
    id: string;
    value: string[];
    placeholder: string;
    onChange: (value: string[]) => void;
}) {
    return (
        <Field label={label} htmlFor={id}>
            <Input
                id={id}
                value={value.join(', ')}
                placeholder={placeholder}
                onChange={(event) =>
                    onChange(parseFilterListInput(event.target.value))
                }
            />
        </Field>
    );
}

function SelectFilter({
    label,
    id,
    value,
    options,
    onChange,
}: {
    label: string;
    id: string;
    value: string;
    options: { value: string; label: string }[];
    onChange: (value: string) => void;
}) {
    return (
        <Field label={label} htmlFor={id}>
            <Select
                value={value || '__all__'}
                onValueChange={(next) => onChange(next === '__all__' ? '' : next)}
            >
                <SelectTrigger id={id} aria-label={label}>
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    <SelectItem value="__all__">All</SelectItem>
                    {options.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </Field>
    );
}

function DateFilter({
    label,
    id,
    value,
    onChange,
    endOfDay = false,
}: {
    label: string;
    id: string;
    value: string | null;
    onChange: (value: string | null) => void;
    endOfDay?: boolean;
}) {
    const date = value ? value.slice(0, 10) : '';
    return (
        <Field label={label} htmlFor={id}>
            <Input
                id={id}
                type="date"
                value={date}
                onChange={(event) =>
                    onChange(
                        event.target.value
                            ? `${event.target.value}T${endOfDay ? '23:59:59' : '00:00:00'}.000Z`
                            : null
                    )
                }
            />
        </Field>
    );
}

function Metric({
    label,
    value,
    loading = false,
    error = null,
}: {
    label: string;
    value: number;
    loading?: boolean;
    error?: Error | null;
}) {
    return (
        <Card className="border">
            <CardHeader className="pb-2">
                <CardTitle className="text-sm text-muted-foreground">
                    {label}
                </CardTitle>
            </CardHeader>
            <CardContent>
                <p className="text-2xl font-semibold">
                    {error ? 'Unavailable' : loading ? '…' : value.toLocaleString()}
                </p>
            </CardContent>
        </Card>
    );
}

function InlineMetric({ label, value }: { label: string; value: number }) {
    return (
        <div className="border-l-2 border-primary/40 pl-3">
            <dt className="text-sm text-muted-foreground">{label}</dt>
            <dd className="mt-1 text-xl font-semibold">{value.toLocaleString()}</dd>
        </div>
    );
}

function DataState({
    title,
    loading,
    validating = false,
    error,
    empty,
    retry,
    children,
}: {
    title: string;
    loading: boolean;
    validating?: boolean;
    error: Error | null;
    empty: boolean;
    retry?: () => Promise<unknown> | void;
    children: ReactNode;
}) {
    return (
        <Card className="border">
            <CardHeader className="flex-row items-center justify-between">
                <CardTitle>{title}</CardTitle>
                {validating && (
                    <span role="status" className="text-xs text-muted-foreground">
                        Refreshing…
                    </span>
                )}
            </CardHeader>
            <CardContent>
                {error ? (
                    <Alert variant="destructive">
                        <AlertTitle>Could not load this data</AlertTitle>
                        <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
                            <span>{error.message}</span>
                            {retry && (
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    aria-label={`Retry ${title.toLowerCase()}`}
                                    disabled={validating}
                                    onClick={() => {
                                        void retry();
                                    }}
                                >
                                    <RefreshCw aria-hidden="true" />
                                    Retry
                                </Button>
                            )}
                        </AlertDescription>
                    </Alert>
                ) : loading ? (
                    <p role="status" className="text-sm text-muted-foreground">
                        Loading {title.toLowerCase()}…
                    </p>
                ) : empty ? (
                    <p className="text-sm text-muted-foreground">
                        No data matches the applied filters.
                    </p>
                ) : (
                    children
                )}
            </CardContent>
        </Card>
    );
}

function LabelLensControl({
    value,
    onChange,
}: {
    value: LabelLens;
    onChange: (value: LabelLens) => void;
}) {
    return (
        <section
            aria-label="Observability label lens"
            className="flex flex-wrap items-center gap-x-5 gap-y-3 rounded-md border bg-card px-4 py-3"
        >
            <p className="text-sm font-medium">Label lens</p>
            <RadioGroup
                aria-label="Label lens"
                className="flex flex-wrap gap-x-5 gap-y-2"
                value={value}
                onValueChange={(next) => {
                    if (
                        next === 'raw_outcomes' ||
                        next === 'approved_snapshots'
                    ) {
                        onChange(next);
                    }
                }}
            >
                <div className="flex items-center gap-2">
                    <RadioGroupItem
                        id="lens-raw-outcomes"
                        value="raw_outcomes"
                    />
                    <Label htmlFor="lens-raw-outcomes">Raw outcomes</Label>
                </div>
                <div className="flex items-center gap-2">
                    <RadioGroupItem
                        id="lens-approved-snapshots"
                        value="approved_snapshots"
                    />
                    <Label htmlFor="lens-approved-snapshots">
                        Approved snapshots
                    </Label>
                </div>
            </RadioGroup>
        </section>
    );
}

function ApprovedSnapshotsState() {
    return (
        <Alert>
            <AlertTitle>Approved snapshot data is unavailable</AlertTitle>
            <AlertDescription>
                The current API exposes raw outcome aggregates and calibration
                readiness. It does not provide a snapshot-backed cohort or
                calibration read model, so approved snapshot metrics cannot be
                shown here.
            </AlertDescription>
        </Alert>
    );
}

function EventExplorer({
    rows,
    loading,
    validating,
    error,
    retryRows,
    selectedId,
    onSelect,
    detail,
}: {
    rows: ObservabilityData['rows'];
    loading: boolean;
    validating: boolean;
    error: Error | null;
    retryRows: () => Promise<unknown> | void;
    selectedId: string | null;
    onSelect: (id: string | null) => void;
    detail: ReturnType<typeof useTechnicalObservabilityEventDetail>;
}) {
    const detailData = detail.detail;
    const sourceRefs = detailData
        ? Object.entries(detailData.source_artifact_refs).filter(
              (entry): entry is [string, string] => typeof entry[1] === 'string'
          )
        : [];

    return (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(300px,1fr)]">
            <DataState
                title="Prediction events"
                loading={loading}
                validating={validating}
                error={error}
                retry={retryRows}
                empty={rows.length === 0}
            >
                <div className="overflow-x-auto">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Event time</TableHead>
                                <TableHead>Ticker</TableHead>
                                <TableHead>Direction</TableHead>
                                <TableHead>Frame</TableHead>
                                <TableHead>Horizon</TableHead>
                                <TableHead>Confidence</TableHead>
                                <TableHead>Raw score</TableHead>
                                <TableHead>Forward return</TableHead>
                                <TableHead>Realized vol</TableHead>
                                <TableHead>MFE</TableHead>
                                <TableHead>MAE</TableHead>
                                <TableHead>Reliability</TableHead>
                                <TableHead>Resolved</TableHead>
                                <TableHead>Quality</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {rows.map((row) => (
                                <TableRow
                                    key={row.event_id}
                                    data-state={
                                        selectedId === row.event_id
                                            ? 'selected'
                                            : undefined
                                    }
                                >
                                    <TableCell>
                                        <button
                                            type="button"
                                            aria-label={`Open event ${row.event_id}`}
                                            className="whitespace-nowrap text-left text-primary underline-offset-4 hover:underline"
                                            onClick={() => onSelect(row.event_id)}
                                        >
                                            {new Date(row.event_time).toLocaleString()}
                                        </button>
                                    </TableCell>
                                    <TableCell>{row.ticker}</TableCell>
                                    <TableCell>{row.direction}</TableCell>
                                    <TableCell>{row.timeframe}</TableCell>
                                    <TableCell>{row.horizon}</TableCell>
                                    <TableCell>{formatNumber(row.confidence)}</TableCell>
                                    <TableCell>{formatMetric(row.raw_score)}</TableCell>
                                    <TableCell>
                                        {formatNumber(row.forward_return)}
                                    </TableCell>
                                    <TableCell>
                                        {formatNumber(row.realized_volatility)}
                                    </TableCell>
                                    <TableCell>{formatNumber(row.mfe)}</TableCell>
                                    <TableCell>{formatNumber(row.mae)}</TableCell>
                                    <TableCell>
                                        {row.reliability_level ?? '—'}
                                    </TableCell>
                                    <TableCell>
                                        {row.resolved_at
                                            ? new Date(
                                                  row.resolved_at
                                              ).toLocaleString()
                                            : 'Unresolved'}
                                    </TableCell>
                                    <TableCell>
                                        {row.data_quality_flags.length ? (
                                            <Badge variant="warning">
                                                {row.data_quality_flags.length} flags
                                            </Badge>
                                        ) : (
                                            <Badge variant="secondary">Clear</Badge>
                                        )}
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </div>
            </DataState>

            <Card className="border">
                <CardHeader className="flex-row items-center justify-between">
                    <CardTitle>Event detail</CardTitle>
                    {selectedId && (
                        <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => onSelect(null)}
                        >
                            Close
                        </Button>
                    )}
                </CardHeader>
                <CardContent>
                    {!selectedId ? (
                        <p className="text-sm text-muted-foreground">
                            Select an event to inspect its stored context and source
                            references.
                        </p>
                    ) : detail.error ? (
                        <Alert variant="destructive">
                            <AlertTitle>Detail unavailable</AlertTitle>
                            <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
                                <span>{detail.error.message}</span>
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    aria-label="Retry event detail"
                                    disabled={detail.isValidating}
                                    onClick={() => {
                                        void detail.retry();
                                    }}
                                >
                                    <RefreshCw aria-hidden="true" />
                                    Retry
                                </Button>
                            </AlertDescription>
                        </Alert>
                    ) : detail.isLoading ? (
                        <p role="status">Loading event detail…</p>
                    ) : detailData ? (
                        <div className="grid gap-4">
                            <dl className="grid gap-3 text-sm sm:grid-cols-2">
                                <Detail label="Ticker" value={detailData.ticker} />
                                <Detail label="Event ID" value={detailData.event_id} />
                                <Detail label="Agent source" value={detailData.agent_source} />
                                <Detail
                                    label="Contract"
                                    value={detailData.feature_contract_version}
                                />
                                <Detail
                                    label="Labeling method"
                                    value={detailData.labeling_method_version ?? '—'}
                                />
                                <Detail
                                    label="Outcome path"
                                    value={detailData.outcome_path_id ?? '—'}
                                />
                                <Detail
                                    label="Resolved at"
                                    value={
                                        detailData.resolved_at
                                            ? new Date(
                                                  detailData.resolved_at
                                              ).toLocaleString()
                                            : 'Unresolved'
                                    }
                                />
                                <Detail
                                    label="Confidence"
                                    value={formatNumber(detailData.confidence)}
                                />
                                <Detail
                                    label="Raw score"
                                    value={formatMetric(detailData.raw_score)}
                                />
                                <Detail
                                    label="Forward return"
                                    value={formatNumber(detailData.forward_return)}
                                />
                                <Detail
                                    label="Realized volatility"
                                    value={formatNumber(
                                        detailData.realized_volatility
                                    )}
                                />
                                <Detail
                                    label="MFE"
                                    value={formatNumber(detailData.mfe)}
                                />
                                <Detail
                                    label="MAE"
                                    value={formatNumber(detailData.mae)}
                                />
                                <Detail
                                    label="Reliability"
                                    value={detailData.reliability_level ?? '—'}
                                />
                            </dl>

                            <div>
                                <h3 className="text-sm font-medium">
                                    Report and source artifacts
                                </h3>
                                <ul className="mt-2 grid gap-2">
                                    <li>
                                        <ArtifactLink
                                            label="Full report"
                                            artifactId={
                                                detailData.full_report_artifact_id
                                            }
                                            runId={detailData.run_id}
                                        />
                                    </li>
                                    {sourceRefs.map(([label, artifactId]) => (
                                        <li key={label}>
                                            <ArtifactLink
                                                label={label.replaceAll('_', ' ')}
                                                artifactId={artifactId}
                                                runId={detailData.run_id}
                                            />
                                        </li>
                                    ))}
                                </ul>
                            </div>

                            <div>
                                <h3 className="text-sm font-medium">
                                    Data quality flags
                                </h3>
                                {detailData.data_quality_flags.length ? (
                                    <ul className="mt-2 flex flex-wrap gap-2">
                                        {detailData.data_quality_flags.map((flag) => (
                                            <li key={flag}>
                                                <Badge variant="warning">{flag}</Badge>
                                            </li>
                                        ))}
                                    </ul>
                                ) : (
                                    <p className="mt-1 text-sm text-muted-foreground">
                                        No quality flags recorded.
                                    </p>
                                )}
                            </div>

                            <Detail
                                label="Context"
                                value={JSON.stringify(
                                    detailData.context_payload,
                                    null,
                                    2
                                )}
                            />
                        </div>
                    ) : (
                        <p className="text-sm text-muted-foreground">
                            No detail available.
                        </p>
                    )}
                </CardContent>
            </Card>
        </div>
    );
}

function ArtifactLink({
    label,
    artifactId,
    runId,
}: {
    label: string;
    artifactId: string;
    runId?: string | null;
}) {
    const href = buildArtifactUrl(artifactId, runId ?? undefined);

    return (
        <a
            className="inline-flex max-w-full items-center gap-2 break-all text-sm text-primary underline-offset-4 hover:underline"
            href={href}
            target="_blank"
            rel="noreferrer"
        >
            <span>
                {label}: {artifactId}
            </span>
            <ExternalLink aria-hidden="true" className="size-4 shrink-0" />
        </a>
    );
}

function Detail({ label, value }: { label: string; value: string }) {
    return (
        <div className="min-w-0">
            <dt className="font-medium text-muted-foreground">{label}</dt>
            <dd className="mt-1 break-all font-mono text-xs">{value}</dd>
        </div>
    );
}

function formatNumber(value: number | null | undefined): string {
    return value == null ? '—' : `${(value * 100).toFixed(2)}%`;
}

function formatMetric(value: number | null | undefined): string {
    return value == null ? '—' : value.toFixed(4);
}
