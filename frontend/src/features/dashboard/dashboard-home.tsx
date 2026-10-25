'use client';

import Link from 'next/link';
import { useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import { Activity, ArrowDownRight, ArrowRight, ArrowUpRight, CircleAlert, Clock3, LoaderCircle, RefreshCw, Search } from 'lucide-react';
import { SWRConfig } from 'swr';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { useDashboardOverview, type PanelState } from './use-dashboard-overview';
import type { DashboardCapabilities, MarketMover, MarketMovers, RecentAnalyses, RecentAnalysis } from './api';

function formatDate(value: string | null): string {
    if (!value) return 'Time unavailable';
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function sourceLabel(value: string): string {
    return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function statusVariant(value: string): 'success' | 'warning' | 'destructive' | 'outline' {
    switch (value) {
        case 'operational':
        case 'fresh':
        case 'completed': return 'success';
        case 'degraded':
        case 'stale':
        case 'waiting': return 'warning';
        case 'unavailable':
        case 'failed':
        case 'cancelled': return 'destructive';
        default: return 'outline';
    }
}

function displayStatus(value: string): string {
    return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function PanelHeading({
    title,
    description,
    onRefresh,
    isRefreshing = false,
}: {
    title: string;
    description: string;
    onRefresh: () => void;
    isRefreshing?: boolean;
}) {
    return (
        <CardHeader className="flex-row items-start justify-between gap-3 border-b border-border/70 px-5 py-4">
            <div className="min-w-0">
                <CardTitle className="text-base">{title}</CardTitle>
                <p className="mt-1 text-xs text-muted-foreground">{description}</p>
            </div>
            <Button variant="ghost" size="icon" onClick={onRefresh} disabled={isRefreshing} aria-label={`Refresh ${title.toLowerCase()}`} title={`Refresh ${title.toLowerCase()}`}>
                {isRefreshing ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <RefreshCw aria-hidden="true" />}
            </Button>
        </CardHeader>
    );
}

function PanelError({ message, onRetry }: { message: string; onRetry: () => void }) {
    return (
        <Alert variant="destructive" role="alert">
            <CircleAlert aria-hidden="true" className="size-4" />
            <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
                <span>{message}</span>
                <Button variant="outline" size="sm" onClick={onRetry}>Retry</Button>
            </AlertDescription>
        </Alert>
    );
}

function RefreshError({ message }: { message: string }) {
    return <Alert variant="warning" role="status" className="mt-3"><AlertDescription>Refresh failed. Showing the last successful response. {message}</AlertDescription></Alert>;
}

function LoadingRows({ count = 3 }: { count?: number }) {
    return (
        <div className="grid gap-4" aria-label="Loading dashboard data" role="status">
            {Array.from({ length: count }, (_, index) => (
                <div key={index} className="grid gap-2 border-b border-border/60 pb-4 last:border-0 last:pb-0">
                    <Skeleton className="h-4 w-2/5" />
                    <Skeleton className="h-3 w-4/5" />
                </div>
            ))}
        </div>
    );
}

function recentAnalysisHref(item: RecentAnalysis): string {
    const params = new URLSearchParams({ thread_id: item.threadId, run_id: item.runId });
    return `/workspace?${params.toString()}`;
}

function RecentAnalysisRow({ item }: { item: RecentAnalysis }) {
    const title = item.ticker || item.companyName || 'Company details unavailable';
    const subtitle = item.ticker && item.companyName ? item.companyName : null;

    return (
        <Link
            href={recentAnalysisHref(item)}
            className="group grid gap-2 border-b border-border/60 py-4 last:border-0 last:pb-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={`Open analysis run ${item.runId}`}
        >
            <div className="flex min-w-0 items-start justify-between gap-3">
                <div className="min-w-0">
                    <p className="truncate font-medium tabular-nums group-hover:text-primary">{title}</p>
                    {subtitle ? <p className="mt-1 truncate text-xs text-muted-foreground">{subtitle}</p> : null}
                </div>
                <Badge variant={statusVariant(item.status)}>{displayStatus(item.status)}</Badge>
            </div>
            <p className="line-clamp-2 text-sm text-muted-foreground">{item.summary ?? 'Summary unavailable.'}</p>
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1"><Clock3 aria-hidden="true" className="size-3.5" />Started {formatDate(item.startedAt)}</span>
                <span className="font-mono">Run {item.runId}</span>
            </div>
        </Link>
    );
}

function RecentAnalysesPanel({
    state,
    onRefresh,
    isLoadingMore,
    loadMoreError,
    onLoadMore,
}: {
    state: PanelState<RecentAnalyses>;
    onRefresh: () => void;
    isLoadingMore: boolean;
    loadMoreError: string | null;
    onLoadMore: () => void;
}) {
    const isRefreshing = state.kind === 'ready' && state.isRefreshing;
    let body: ReactNode;
    if (state.kind === 'loading') {
        body = <LoadingRows />;
    } else if (state.kind === 'error') {
        body = <PanelError message={state.message} onRetry={onRefresh} />;
    } else if (state.data.items.length === 0) {
        body = <EmptyState className="min-h-40" icon={<Activity />} title="No analyses yet" description="Completed and in-progress runs will appear here." />;
    } else {
        body = (
            <>
                <div>{state.data.items.map((item) => <RecentAnalysisRow key={`${item.threadId}:${item.runId}`} item={item} />)}</div>
                {state.refreshError ? <RefreshError message={state.refreshError} /> : null}
                {loadMoreError ? <PanelError message={loadMoreError} onRetry={onLoadMore} /> : null}
                {state.data.nextCursor ? (
                    <Button variant="outline" className="mt-4 w-full" onClick={onLoadMore} disabled={isLoadingMore}>
                        {isLoadingMore ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : null}
                        {isLoadingMore ? 'Loading more...' : 'Load more analyses'}
                    </Button>
                ) : null}
            </>
        );
    }

    return (
        <Card className="min-w-0 overflow-hidden">
            <PanelHeading title="Recent analyses" description="Your latest analysis runs" onRefresh={onRefresh} isRefreshing={isRefreshing} />
            <CardContent className="p-5">{body}</CardContent>
        </Card>
    );
}

function formatPrice(mover: MarketMover): string {
    if (mover.currency) {
        try {
            return new Intl.NumberFormat(undefined, { style: 'currency', currency: mover.currency, maximumFractionDigits: 2 }).format(mover.price);
        } catch { /* Invalid currency metadata should not hide a real quote. */ }
    }
    return mover.price.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function MarketMoverRow({ item }: { item: MarketMover }) {
    const isPositive = item.changeAbsolute >= 0;
    const ChangeIcon = isPositive ? ArrowUpRight : ArrowDownRight;
    return (
        <div className="grid gap-2 border-b border-border/60 py-4 last:border-0 last:pb-0">
            <div className="flex min-w-0 items-start justify-between gap-3">
                <div className="min-w-0">
                    <p className="truncate font-medium tabular-nums">{item.symbol}</p>
                    <p className="mt-1 truncate text-xs text-muted-foreground">{item.name}</p>
                </div>
                <div className="shrink-0 text-right">
                    <p className="font-medium tabular-nums">{formatPrice(item)}</p>
                    <p className={`mt-1 inline-flex items-center gap-1 text-xs tabular-nums ${isPositive ? 'text-success' : 'text-destructive'}`}>
                        <ChangeIcon aria-hidden="true" className="size-3" />
                        {item.changeAbsolute > 0 ? '+' : ''}{item.changeAbsolute.toLocaleString(undefined, { maximumFractionDigits: 2 })} ({item.changePercent > 0 ? '+' : ''}{item.changePercent.toFixed(2)}%)
                    </p>
                </div>
            </div>
            <div className="flex flex-wrap justify-between gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span>{item.marketState ? displayStatus(item.marketState) : 'Market state unavailable'}</span>
                <span>Quote {formatDate(item.quoteTime)}</span>
            </div>
        </div>
    );
}

function MarketMoversPanel({ state, onRefresh }: { state: PanelState<MarketMovers>; onRefresh: () => void }) {
    const isRefreshing = state.kind === 'ready' && state.isRefreshing;
    let body: ReactNode;
    if (state.kind === 'loading') {
        body = <LoadingRows />;
    } else if (state.kind === 'error') {
        body = <PanelError message={state.message} onRetry={onRefresh} />;
    } else if (state.data.status === 'unavailable' && state.data.items.length === 0) {
        body = <EmptyState className="min-h-40" icon={<CircleAlert />} title="Quotes unavailable" description={state.data.errorCode ? `The market data source reported ${state.data.errorCode}.` : 'The market data source did not return quotes.'} action={<Button variant="outline" size="sm" onClick={onRefresh}>Retry quotes</Button>} />;
    } else if (state.data.items.length === 0) {
        body = <EmptyState className="min-h-40" icon={<Activity />} title="No market movers" description="The source returned no quote rows." />;
    } else {
        body = (
            <>
                <div>{state.data.items.map((item) => <MarketMoverRow key={item.symbol} item={item} />)}</div>
                <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                    <span>{sourceLabel(state.data.source)}{state.data.status === 'stale' ? ' · Stale data' : ''}</span>
                    <span>Fetched {formatDate(state.data.fetchedAt)}</span>
                </div>
                {state.data.status === 'stale' ? <Alert variant="warning" role="status" className="mt-3"><AlertDescription>Showing the last available market quotes.</AlertDescription></Alert> : null}
                {state.refreshError ? <RefreshError message={state.refreshError} /> : null}
            </>
        );
    }
    return (
        <Card className="min-w-0 overflow-hidden">
            <PanelHeading title="Most active" description="Market activity from the connected source" onRefresh={onRefresh} isRefreshing={isRefreshing} />
            <CardContent className="p-5">{body}</CardContent>
        </Card>
    );
}

function CapabilitiesPanel({ state, onRefresh }: { state: PanelState<DashboardCapabilities>; onRefresh: () => void }) {
    const isRefreshing = state.kind === 'ready' && state.isRefreshing;
    let body: ReactNode;
    if (state.kind === 'loading') {
        body = <LoadingRows count={4} />;
    } else if (state.kind === 'error') {
        body = <PanelError message={state.message} onRetry={onRefresh} />;
    } else if (state.data.capabilities.length === 0) {
        body = <EmptyState className="min-h-40" icon={<Activity />} title="No capability checks" description="The backend did not report any capability probes." />;
    } else {
        body = (
            <>
                <div className="mb-4 flex items-center justify-between gap-3">
                    <p className="text-xs text-muted-foreground">Overall status</p>
                    <Badge variant={statusVariant(state.data.status)}>{displayStatus(state.data.status)}</Badge>
                </div>
                <div className="grid gap-4">
                    {state.data.capabilities.map((item) => (
                        <div key={item.id} className="grid gap-2 border-b border-border/60 pb-4 last:border-0 last:pb-0">
                            <div className="flex min-w-0 items-start justify-between gap-3">
                                <p className="truncate font-medium">{displayStatus(item.id)}</p>
                                <Badge variant={statusVariant(item.status)}>{displayStatus(item.status)}</Badge>
                            </div>
                            <p className="text-xs text-muted-foreground">{item.detail ?? `Source: ${item.source}`}</p>
                            <p className="text-xs text-muted-foreground">Checked {formatDate(item.checkedAt)}</p>
                        </div>
                    ))}
                </div>
                {state.refreshError ? <RefreshError message={state.refreshError} /> : null}
            </>
        );
    }
    return (
        <Card className="min-w-0 overflow-hidden">
            <PanelHeading title="Service capabilities" description="Backend readiness checks" onRefresh={onRefresh} isRefreshing={isRefreshing} />
            <CardContent className="p-5">{body}</CardContent>
        </Card>
    );
}

export function DashboardOverview() {
    const dashboard = useDashboardOverview();

    return (
        <section className="grid gap-5 py-7 lg:grid-cols-3" aria-label="Dashboard overview">
            <RecentAnalysesPanel
                state={dashboard.recentAnalyses}
                onRefresh={() => void dashboard.refreshRecentAnalyses()}
                isLoadingMore={dashboard.isLoadingMore}
                loadMoreError={dashboard.loadMoreError}
                onLoadMore={() => void dashboard.loadMoreRecentAnalyses()}
            />
            <MarketMoversPanel state={dashboard.marketMovers} onRefresh={() => void dashboard.refreshMarketMovers()} />
            <CapabilitiesPanel state={dashboard.capabilities} onRefresh={() => void dashboard.refreshCapabilities()} />
        </section>
    );
}

export function DashboardHome() {
    const provider = useMemo(() => () => new Map(), []);
    return <SWRConfig value={{ provider }}><DashboardHomeContent /></SWRConfig>;
}

function DashboardHomeContent() {
    const router = useRouter();
    const [ticker, setTicker] = useState('');
    const [isNavigating, setIsNavigating] = useState(false);
    const [tickerError, setTickerError] = useState<string | null>(null);

    function startAnalysis(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        const query = ticker.trim();
        if (!query) {
            setTickerError('Enter a company name or ticker to start an analysis.');
            return;
        }
        setTickerError(null);
        setIsNavigating(true);
        router.push(`/workspace?ticker=${encodeURIComponent(query)}`);
    }

    return (
        <main className="min-h-[calc(100vh-4rem)] bg-background px-4 py-8 sm:px-8 lg:px-10">
            <div className="mx-auto max-w-6xl">
                <section className="border-b border-border pb-8 sm:pb-10" aria-labelledby="home-title">
                    <p className="text-sm font-medium text-primary">Investment research</p>
                    <h1 id="home-title" className="mt-2 max-w-3xl font-headline text-3xl font-semibold sm:text-4xl">Start a company analysis</h1>
                    <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">Enter a company name or ticker to open the analysis workspace. The workflow resolves the company and asks you to confirm when ticker matches are ambiguous.</p>
                    <form onSubmit={startAnalysis} className="mt-7 grid max-w-2xl gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                        <Field label="Company name or ticker" htmlFor="analysis-ticker" description="For example, Apple or BRK.B.">
                            <div className="flex items-center gap-2 border-b border-input focus-within:border-ring">
                                <Search aria-hidden="true" className="ml-1 size-4 text-muted-foreground" />
                                <Input id="analysis-ticker" value={ticker} onChange={(event) => setTicker(event.target.value)} placeholder="Enter a company or ticker" autoComplete="off" disabled={isNavigating} className="border-0 focus-visible:border-0 focus-visible:shadow-none" />
                            </div>
                        </Field>
                        <Button type="submit" disabled={isNavigating} className="min-w-40">
                            {isNavigating ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <ArrowRight aria-hidden="true" />}
                            {isNavigating ? 'Opening workspace...' : 'Analyze company'}
                        </Button>
                    </form>
                    {tickerError ? <Alert className="mt-4 max-w-2xl" variant="destructive" role="alert"><AlertDescription>{tickerError}</AlertDescription></Alert> : null}
                </section>

                <DashboardOverview />
            </div>
        </main>
    );
}
