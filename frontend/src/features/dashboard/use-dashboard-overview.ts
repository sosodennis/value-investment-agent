'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import {
    DashboardApiError,
    getDashboardCapabilities,
    getMarketMovers,
    getRecentAnalyses,
    type DashboardCapabilities,
    type MarketMovers,
    type RecentAnalyses,
} from './api';

export type PanelState<T> =
    | { kind: 'loading' }
    | { kind: 'error'; message: string }
    | { kind: 'ready'; data: T; isRefreshing: boolean; refreshError: string | null };

function errorMessage(cause: unknown): string {
    return cause instanceof DashboardApiError
        ? cause.message
        : 'The dashboard data could not be loaded.';
}

export function useDashboardOverview() {
    const [recentAnalyses, setRecentAnalyses] = useState<PanelState<RecentAnalyses>>({ kind: 'loading' });
    const [marketMovers, setMarketMovers] = useState<PanelState<MarketMovers>>({ kind: 'loading' });
    const [capabilities, setCapabilities] = useState<PanelState<DashboardCapabilities>>({ kind: 'loading' });
    const [isLoadingMore, setIsLoadingMore] = useState(false);
    const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
    const recentRequestInFlight = useRef(false);

    const refreshRecentAnalyses = useCallback(async () => {
        if (recentRequestInFlight.current) return;
        recentRequestInFlight.current = true;
        setRecentAnalyses((current) => current.kind === 'ready'
            ? { ...current, isRefreshing: true, refreshError: null }
            : { kind: 'loading' });
        setLoadMoreError(null);
        try {
            const data = await getRecentAnalyses({ limit: 10 });
            setRecentAnalyses({ kind: 'ready', data, isRefreshing: false, refreshError: null });
        } catch (cause) {
            const message = errorMessage(cause);
            setRecentAnalyses((current) => current.kind === 'ready'
                ? { ...current, isRefreshing: false, refreshError: message }
                : { kind: 'error', message });
        } finally {
            recentRequestInFlight.current = false;
        }
    }, []);

    const loadMoreRecentAnalyses = useCallback(async () => {
        if (recentRequestInFlight.current || recentAnalyses.kind !== 'ready' || !recentAnalyses.data.nextCursor) return;
        recentRequestInFlight.current = true;
        setIsLoadingMore(true);
        setLoadMoreError(null);
        try {
            const nextPage = await getRecentAnalyses({ limit: 10, next_cursor: recentAnalyses.data.nextCursor });
            setRecentAnalyses((current) => {
                if (current.kind !== 'ready') return current;
                const seen = new Set(current.data.items.map((item) => `${item.threadId}\u0000${item.runId}`));
                const newItems = nextPage.items.filter((item) => !seen.has(`${item.threadId}\u0000${item.runId}`));
                return {
                    ...current,
                    data: {
                        ...nextPage,
                        items: [...current.data.items, ...newItems],
                    },
                };
            });
        } catch (cause) {
            setLoadMoreError(errorMessage(cause));
        } finally {
            setIsLoadingMore(false);
            recentRequestInFlight.current = false;
        }
    }, [recentAnalyses]);

    const refreshMarketMovers = useCallback(async () => {
        setMarketMovers((current) => current.kind === 'ready'
            ? { ...current, isRefreshing: true, refreshError: null }
            : { kind: 'loading' });
        try {
            const data = await getMarketMovers();
            setMarketMovers({ kind: 'ready', data, isRefreshing: false, refreshError: null });
        } catch (cause) {
            const message = errorMessage(cause);
            setMarketMovers((current) => current.kind === 'ready'
                ? { ...current, isRefreshing: false, refreshError: message }
                : { kind: 'error', message });
        }
    }, []);

    const refreshCapabilities = useCallback(async () => {
        setCapabilities((current) => current.kind === 'ready'
            ? { ...current, isRefreshing: true, refreshError: null }
            : { kind: 'loading' });
        try {
            const data = await getDashboardCapabilities();
            setCapabilities({ kind: 'ready', data, isRefreshing: false, refreshError: null });
        } catch (cause) {
            const message = errorMessage(cause);
            setCapabilities((current) => current.kind === 'ready'
                ? { ...current, isRefreshing: false, refreshError: message }
                : { kind: 'error', message });
        }
    }, []);

    useEffect(() => {
        let cancelled = false;
        const timer = window.setTimeout(() => {
            if (cancelled) return;
            void refreshRecentAnalyses();
            void refreshMarketMovers();
            void refreshCapabilities();
        }, 0);
        return () => {
            cancelled = true;
            window.clearTimeout(timer);
        };
    }, [refreshCapabilities, refreshMarketMovers, refreshRecentAnalyses]);

    return {
        recentAnalyses,
        marketMovers,
        capabilities,
        isLoadingMore,
        loadMoreError,
        refreshRecentAnalyses,
        refreshMarketMovers,
        refreshCapabilities,
        loadMoreRecentAnalyses,
    };
}
