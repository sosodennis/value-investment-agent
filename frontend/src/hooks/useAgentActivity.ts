import { useCallback, useEffect, useMemo, useState } from 'react';
import { clientLogger } from '@/lib/logger';
import {
    ActivitySegment,
    StatusHistoryEntry,
    parseActivitySegments,
    parseApiErrorMessage,
} from '@/types/protocol';

const API_URL = process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000';

export type ActivitySegmentView = StatusHistoryEntry & {
    isCurrent: boolean;
    runId: string;
    startedAt: number;
    endedAt: number | null;
};

type ActivityCacheEntry = {
    events: ActivitySegmentView[];
    hasMore: boolean;
};

const activityCache = new Map<string, ActivityCacheEntry>();

const readErrorMessage = async (
    response: Response,
    fallback: string
): Promise<string> => {
    try {
        const raw: unknown = await response.json();
        return parseApiErrorMessage(raw) || `${fallback} (HTTP ${response.status})`;
    } catch {
        return `${fallback} (HTTP ${response.status})`;
    }
};

const mergeEvents = (
    existing: ActivitySegmentView[],
    incoming: ActivitySegmentView[]
): ActivitySegmentView[] => {
    if (incoming.length === 0) return existing;
    const seen = new Set(existing.map((entry) => entry.id));
    const merged = [...existing];
    for (const entry of incoming) {
        if (seen.has(entry.id)) continue;
        merged.push(entry);
        seen.add(entry.id);
    }
    return merged.sort((a, b) => b.timestamp - a.timestamp);
};

const resolveBeforeTs = (events: ActivitySegmentView[]): string | undefined => {
    if (events.length === 0) return undefined;
    const oldest = events[events.length - 1];
    return new Date(oldest.timestamp).toISOString();
};

const toSegmentView = (segment: ActivitySegment): ActivitySegmentView => ({
    id: segment.id,
    node: segment.node,
    agentId: segment.agentId,
    status: segment.status,
    timestamp: Date.parse(segment.updated_at),
    isCurrent: segment.is_current,
    runId: segment.runId,
    startedAt: Date.parse(segment.started_at),
    endedAt: segment.ended_at ? Date.parse(segment.ended_at) : null,
});

export const useAgentActivity = (
    threadId: string | null | undefined,
    agentId: string | null | undefined,
    limit: number = 5,
    pageSize?: number
) => {
    const resolvedPageSize =
        typeof pageSize === 'number' && Number.isFinite(pageSize) && pageSize > 0
            ? pageSize
            : limit;
    const cacheKey = useMemo(() => {
        if (!threadId || !agentId) return null;
        return `${threadId}:${agentId}`;
    }, [threadId, agentId]);

    const [events, setEvents] = useState<ActivitySegmentView[]>(() => {
        if (!cacheKey) return [];
        return activityCache.get(cacheKey)?.events ?? [];
    });
    const [hasMore, setHasMore] = useState<boolean>(() => {
        if (!cacheKey) return true;
        return activityCache.get(cacheKey)?.hasMore ?? true;
    });
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const fetchActivity = useCallback(
        async (
            beforeTs?: string,
            overrideLimit?: number
        ): Promise<ActivitySegmentView[]> => {
            if (!threadId || !agentId) return [];
            const url = new URL(`${API_URL}/thread/${threadId}/activity`);
            url.searchParams.set('agent_id', agentId);
            url.searchParams.set('limit', String(overrideLimit ?? limit));
            if (beforeTs) {
                url.searchParams.set('before_updated_at', beforeTs);
            }
            const response = await fetch(url.toString());
            if (!response.ok) {
                throw new Error(
                    await readErrorMessage(response, 'Failed to fetch activity')
                );
            }
            const data: unknown = await response.json();
            return parseActivitySegments(
                data,
                'agent activity response'
            ).map(toSegmentView);
        },
        [agentId, limit, threadId]
    );

    const refresh = useCallback(async () => {
        if (!cacheKey || !threadId || !agentId) return;
        setIsLoading(true);
        setError(null);
        try {
            const data = await fetchActivity();
            const nextHasMore = data.length >= limit;
            activityCache.set(cacheKey, { events: data, hasMore: nextHasMore });
            setEvents(data);
            setHasMore(nextHasMore);
        } catch (err) {
            const message =
                err instanceof Error ? err.message : 'Failed to fetch activity.';
            clientLogger.error('agent_activity.fetch_error', {
                threadId,
                agentId,
                error: message,
            });
            setError(message);
        } finally {
            setIsLoading(false);
        }
    }, [agentId, cacheKey, fetchActivity, limit, threadId]);

    const loadMore = useCallback(
        async (beforeTs?: string) => {
            if (!cacheKey || !threadId || !agentId) return;
            if (isLoading) return;
            setIsLoading(true);
            setError(null);
            try {
                const cursor = beforeTs ?? resolveBeforeTs(events);
                if (!cursor) {
                    setIsLoading(false);
                    return;
                }
                const data = await fetchActivity(cursor, resolvedPageSize);
                const nextHasMore = data.length >= resolvedPageSize;
                setEvents((prev) => {
                    const merged = mergeEvents(prev, data);
                    activityCache.set(cacheKey, {
                        events: merged,
                        hasMore: nextHasMore,
                    });
                    return merged;
                });
                setHasMore(nextHasMore);
            } catch (err) {
                const message =
                    err instanceof Error ? err.message : 'Failed to fetch activity.';
                clientLogger.error('agent_activity.fetch_more_error', {
                    threadId,
                    agentId,
                    error: message,
                });
                setError(message);
            } finally {
                setIsLoading(false);
            }
        },
        [
            agentId,
            cacheKey,
            events,
            fetchActivity,
            isLoading,
            resolvedPageSize,
            threadId,
        ]
    );

    useEffect(() => {
        if (!cacheKey) {
            setEvents([]);
            setHasMore(true);
            setError(null);
            return;
        }
        const cached = activityCache.get(cacheKey);
        if (cached) {
            setEvents(cached.events);
            setHasMore(cached.hasMore);
            setError(null);
            if (cached.events.length >= limit) {
                return;
            }
        }
        void refresh();
    }, [cacheKey, limit, refresh]);

    return {
        events,
        hasMore,
        isLoading,
        error,
        refresh,
        loadMore,
    };
};
