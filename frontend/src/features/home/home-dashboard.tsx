'use client';

import Link from 'next/link';
import { ArrowUpRight, RefreshCw } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';
import { HomeApiError } from './home-api';
import { useCapabilities, useMarketMovers, useRecentAnalyses } from './use-home-dashboard';

const capabilityVariant = {
    operational: 'success',
    degraded: 'warning',
    unavailable: 'destructive',
    unknown: 'outline',
} as const;

const marketVariant = { fresh: 'success', stale: 'warning', unavailable: 'destructive' } as const;

export function HomeDashboard() {
    const recent = useRecentAnalyses();
    const market = useMarketMovers();
    const capabilities = useCapabilities();

    return (
        <section aria-label="Dashboard" className="grid gap-6 py-7 xl:grid-cols-[minmax(0,1.15fr)_minmax(20rem,0.85fr)]">
            <div className="min-w-0 space-y-6">
                <Card>
                    <CardHeader className="border-b px-5 py-4">
                        <CardTitle className="text-base">Recent analyses</CardTitle>
                    </CardHeader>
                    <CardContent className="p-0">
                        {recent.isLoading ? <LoadingRows label="Recent analyses" /> : null}
                        {recent.error ? <ResourceError error={recent.error} retry={recent.retry} isRetrying={recent.isValidating} resource="recent analyses" /> : null}
                        {recent.data?.items.length === 0 ? (
                            <EmptyState className="px-5 py-8" title="No analyses yet" description="Completed and active analysis runs will appear here." />
                        ) : null}
                        {recent.data?.items.length ? (
                            <ul className="divide-y">
                                {recent.data.items.map((analysis) => {
                                    const label = analysis.company_name || analysis.ticker || analysis.thread_id;
                                    const query = new URLSearchParams({
                                        thread_id: analysis.thread_id,
                                        run_id: analysis.run_id,
                                    });
                                    return (
                                        <li key={`${analysis.thread_id}:${analysis.run_id}`}>
                                            <Link
                                                href={`/workspace?${query.toString()}`}
                                                className="grid min-h-20 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-5 py-4 transition-colors hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                                                aria-label={`Open ${label} analysis run ${analysis.run_id}`}
                                            >
                                                <span className="min-w-0">
                                                    <span className="flex flex-wrap items-center gap-2">
                                                        <span className="truncate text-sm font-medium">{label}</span>
                                                        {analysis.ticker && analysis.company_name ? <span className="font-mono text-xs text-muted-foreground">{analysis.ticker}</span> : null}
                                                    </span>
                                                    <span className="mt-1 block truncate text-xs text-muted-foreground">
                                                        {analysis.summary || `Updated ${formatDate(analysis.updated_at)}`}
                                                    </span>
                                                </span>
                                                <span className="flex items-center gap-2">
                                                    <Badge variant={statusVariant(analysis.status)}>{analysis.status}</Badge>
                                                    <ArrowUpRight aria-hidden="true" className="size-4 text-muted-foreground" />
                                                </span>
                                            </Link>
                                        </li>
                                    );
                                })}
                            </ul>
                        ) : null}
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader className="flex-row items-center justify-between border-b px-5 py-4">
                        <CardTitle className="text-base">Agent availability</CardTitle>
                        <span className="text-xs text-muted-foreground">Checked {formatDate(capabilities.data?.checked_at)}</span>
                    </CardHeader>
                    <CardContent className="p-0">
                        {capabilities.isLoading ? <LoadingRows label="Agent availability" /> : null}
                        {capabilities.error ? <ResourceError error={capabilities.error} retry={capabilities.retry} isRetrying={capabilities.isValidating} resource="agent availability" /> : null}
                        {capabilities.data?.items.length === 0 ? (
                            <EmptyState className="px-5 py-7" title="No capability checks available" description="Availability will appear after the service reports its checks." />
                        ) : null}
                        {capabilities.data?.items.length ? (
                            <ul className="divide-y">
                                {capabilities.data.items.map((item) => (
                                    <li key={item.id} className="flex min-h-14 items-center justify-between gap-4 px-5 py-3">
                                        <span className="min-w-0">
                                            <span className="block truncate text-sm font-medium">{item.label}</span>
                                            <span className="block truncate text-xs text-muted-foreground">{item.source} · checked {formatDate(item.checked_at)}</span>
                                        </span>
                                        <Badge variant={capabilityVariant[item.status]}>{item.status}</Badge>
                                    </li>
                                ))}
                            </ul>
                        ) : null}
                    </CardContent>
                </Card>
            </div>

            <Card className="min-w-0 self-start">
                <CardHeader className="border-b px-5 py-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                            <CardTitle className="text-base">Most active stocks</CardTitle>
                            <p className="mt-1 text-xs text-muted-foreground">
                                {market.data ? `${market.data.source} · ${market.data.status} · as of ${formatDate(market.data.as_of)}` : 'Market quote feed'}
                            </p>
                        </div>
                        {market.data ? <Badge variant={marketVariant[market.data.status]}>{market.data.status}</Badge> : null}
                    </div>
                    {market.data ? <p className="mt-2 text-xs text-muted-foreground">Fetched {formatDate(market.data.fetched_at)}</p> : null}
                </CardHeader>
                <CardContent className="p-0">
                    {market.isLoading ? <LoadingRows label="Most active stocks" /> : null}
                    {market.error ? <ResourceError error={market.error} retry={market.retry} isRetrying={market.isValidating} resource="market data" /> : null}
                    {market.data?.status === 'unavailable' ? (
                        <div className="space-y-3 p-5">
                            <p className="text-sm text-muted-foreground">Market quotes are currently unavailable{market.data.error_code ? ` (${market.data.error_code})` : ''}.</p>
                            <Button variant="outline" size="sm" onClick={() => void market.retry()} disabled={market.isValidating}>
                                <RefreshCw className={market.isValidating ? 'animate-spin' : undefined} />Refresh quotes
                            </Button>
                        </div>
                    ) : null}
                    {market.data?.status !== 'unavailable' && market.data?.items.length === 0 ? (
                        <EmptyState className="px-5 py-8" title="No market quotes available" description="The source returned no active stocks for this update." />
                    ) : null}
                    {market.data?.items.length ? (
                        <ul className="divide-y">
                            {market.data.items.map((item) => (
                                <li key={item.symbol} className="grid min-h-16 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-5 py-3">
                                    <span className="min-w-0">
                                        <span className="block truncate font-mono text-sm font-semibold">{item.symbol}</span>
                                        <span className="block truncate text-xs text-muted-foreground">{item.name} · {item.market_state}</span>
                                    </span>
                                    <span className="text-right tabular-nums">
                                        <span className="block text-sm font-medium">{formatMoney(item.price, item.currency)}</span>
                                        <span className={`block text-xs ${item.change_absolute < 0 ? 'text-destructive' : 'text-success'}`}>
                                            {formatSigned(item.change_absolute, item.currency)} ({formatSigned(item.change_percent, '%')})
                                        </span>
                                    </span>
                                </li>
                            ))}
                        </ul>
                    ) : null}
                    {market.data?.status === 'stale' ? <p className="border-t px-5 py-3 text-xs text-warning">Showing the last available quotes; source data may be delayed.</p> : null}
                </CardContent>
            </Card>
        </section>
    );
}

function ResourceError({ error, retry, isRetrying, resource }: {
    error: HomeApiError;
    retry: () => Promise<unknown>;
    isRetrying: boolean;
    resource: string;
}) {
    const authError = error.status === 401 || error.status === 403;
    return (
        <Alert variant="destructive" role="alert" className="m-4">
            <AlertTitle>{authError ? 'Sign-in required' : `${resource} unavailable`}</AlertTitle>
            <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
                <span>{authError ? 'Your session may have expired.' : error.message}</span>
                {authError ? (
                    <Link className="text-sm font-medium underline underline-offset-4" href={`/login?next=${encodeURIComponent('/')}`}>Sign in</Link>
                ) : (
                    <Button variant="outline" size="sm" onClick={() => void retry()} disabled={isRetrying}>
                        <RefreshCw className={isRetrying ? 'animate-spin' : undefined} />Retry
                    </Button>
                )}
            </AlertDescription>
        </Alert>
    );
}

function LoadingRows({ label }: { label: string }) {
    return (
        <div className="space-y-3 p-5" aria-label={`Loading ${label}`}>
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-4/5" />
        </div>
    );
}

function statusVariant(status: string): 'outline' | 'secondary' | 'success' | 'warning' | 'destructive' {
    const normalized = status.toLowerCase();
    if (['completed', 'complete', 'done'].includes(normalized)) return 'success';
    if (['running', 'queued', 'waiting', 'active'].includes(normalized)) return 'secondary';
    if (['failed', 'cancelled', 'canceled'].includes(normalized)) return 'destructive';
    return 'outline';
}

function formatDate(value: string | undefined): string {
    if (!value) return 'not reported';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
    }).format(date);
}

function formatMoney(value: number, currency: string): string {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 2 }).format(value);
}

function formatSigned(value: number, unit: string): string {
    const sign = value > 0 ? '+' : '';
    if (unit === '%') return `${sign}${value.toFixed(2)}%`;
    return `${sign}${new Intl.NumberFormat(undefined, { style: 'currency', currency: unit, maximumFractionDigits: 2 }).format(value)}`;
}
