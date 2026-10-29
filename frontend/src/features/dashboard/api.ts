import type { components, operations } from '@/types/generated/api-contract';
import { parseApiErrorMessage } from '@/types/protocol';

type RecentAnalysesWire = components['schemas']['RecentAnalysesResponse'];
type RecentAnalysisWire = components['schemas']['RecentAnalysisItem'];
type MarketMoversWire = components['schemas']['MarketMoversResponse'];
type MarketMoverWire = components['schemas']['MarketMoverItem'];
type DashboardCapabilitiesWire = components['schemas']['DashboardCapabilities'];
type CapabilityWire = components['schemas']['CapabilityItem'];
type DashboardStatus = components['schemas']['DashboardStatus'];
type RecentAnalysesQuery = NonNullable<operations['recent_analyses_api_v1_dashboard_recent_analyses_get']['parameters']['query']>;

export type RecentAnalysis = Omit<RecentAnalysisWire, 'thread_id' | 'run_id' | 'started_at' | 'updated_at' | 'company_name'> & {
    threadId: string;
    runId: string;
    startedAt: string | null;
    updatedAt: string | null;
    companyName: string | null;
};

export type RecentAnalyses = Omit<RecentAnalysesWire, 'fetched_at' | 'items' | 'next_cursor'> & {
    fetchedAt: string;
    items: RecentAnalysis[];
    nextCursor: string | null;
};

export type MarketMover = Omit<MarketMoverWire, 'change_absolute' | 'change_percent' | 'market_state' | 'quote_time'> & {
    changeAbsolute: number;
    changePercent: number;
    marketState: string | null;
    quoteTime: string | null;
};

export type MarketMovers = Omit<MarketMoversWire, 'fetched_at' | 'items' | 'error_code'> & {
    fetchedAt: string | null;
    items: MarketMover[];
    errorCode: string | null;
};

export type Capability = Omit<CapabilityWire, 'checked_at'> & { checkedAt: string };
export type DashboardCapabilities = Omit<DashboardCapabilitiesWire, 'checked_at' | 'capabilities'> & {
    checkedAt: string;
    capabilities: Capability[];
};

export class DashboardApiError extends Error {
    constructor(message: string, readonly status: number) {
        super(message);
        this.name = 'DashboardApiError';
    }
}

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function record(value: unknown, context: string): UnknownRecord {
    if (!isRecord(value)) throw new TypeError(`${context} must be an object.`);
    return value;
}

function string(value: unknown, context: string): string {
    if (typeof value !== 'string') throw new TypeError(`${context} must be a string.`);
    return value;
}

function nullableString(value: unknown, context: string): string | null {
    if (value === undefined || value === null) return null;
    return string(value, context);
}

function dateTime(value: unknown, context: string): string {
    const parsed = string(value, context);
    if (!Number.isFinite(Date.parse(parsed))) throw new TypeError(`${context} must be a valid date-time.`);
    return parsed;
}

function nullableDateTime(value: unknown, context: string): string | null {
    if (value === undefined || value === null) return null;
    return dateTime(value, context);
}

function finiteNumber(value: unknown, context: string): number {
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new TypeError(`${context} must be a finite number.`);
    return value;
}

function array(value: unknown, context: string): unknown[] {
    if (!Array.isArray(value)) throw new TypeError(`${context} must be an array.`);
    return value;
}

function dashboardStatus(value: unknown, context: string): DashboardStatus {
    if (value === 'operational' || value === 'degraded' || value === 'unavailable' || value === 'unknown') return value;
    throw new TypeError(`${context} has an unsupported status.`);
}

function parseRecentAnalysis(value: unknown, context: string): RecentAnalysis {
    const item = record(value, context);
    const status = item.status;
    if (status !== 'queued' && status !== 'running' && status !== 'waiting' && status !== 'completed' && status !== 'failed' && status !== 'cancelled' && status !== 'unknown') {
        throw new TypeError(`${context}.status has an unsupported value.`);
    }
    return {
        threadId: string(item.thread_id, `${context}.thread_id`),
        runId: string(item.run_id, `${context}.run_id`),
        status,
        startedAt: nullableDateTime(item.started_at, `${context}.started_at`),
        updatedAt: nullableDateTime(item.updated_at, `${context}.updated_at`),
        ticker: nullableString(item.ticker, `${context}.ticker`),
        companyName: nullableString(item.company_name, `${context}.company_name`),
        summary: nullableString(item.summary, `${context}.summary`),
    };
}

export function parseRecentAnalyses(value: unknown): RecentAnalyses {
    const response = record(value, 'recent_analyses');
    if (response.source !== 'analysis_runtime') throw new TypeError('recent_analyses.source is unsupported.');
    return {
        source: 'analysis_runtime',
        fetchedAt: dateTime(response.fetched_at, 'recent_analyses.fetched_at'),
        items: array(response.items, 'recent_analyses.items').map((item, index) => parseRecentAnalysis(item, `recent_analyses.items[${index}]`)),
        nextCursor: nullableString(response.next_cursor, 'recent_analyses.next_cursor'),
    };
}

function parseMarketMover(value: unknown, context: string): MarketMover {
    const item = record(value, context);
    return {
        symbol: string(item.symbol, `${context}.symbol`),
        name: string(item.name, `${context}.name`),
        price: finiteNumber(item.price, `${context}.price`),
        changeAbsolute: finiteNumber(item.change_absolute, `${context}.change_absolute`),
        changePercent: finiteNumber(item.change_percent, `${context}.change_percent`),
        currency: nullableString(item.currency, `${context}.currency`),
        marketState: nullableString(item.market_state, `${context}.market_state`),
        quoteTime: nullableDateTime(item.quote_time, `${context}.quote_time`),
    };
}

export function parseMarketMovers(value: unknown): MarketMovers {
    const response = record(value, 'market_movers');
    const status = response.status;
    if (status !== 'fresh' && status !== 'stale' && status !== 'unavailable') throw new TypeError('market_movers.status is unsupported.');
    return {
        source: response.source === undefined ? 'yahoo_finance' : string(response.source, 'market_movers.source'),
        status,
        fetchedAt: nullableDateTime(response.fetched_at, 'market_movers.fetched_at'),
        items: array(response.items === undefined ? [] : response.items, 'market_movers.items').map((item, index) => parseMarketMover(item, `market_movers.items[${index}]`)),
        errorCode: nullableString(response.error_code, 'market_movers.error_code'),
    };
}

function parseCapability(value: unknown, context: string): Capability {
    const item = record(value, context);
    return {
        id: string(item.id, `${context}.id`),
        status: dashboardStatus(item.status, `${context}.status`),
        source: string(item.source, `${context}.source`),
        checkedAt: dateTime(item.checked_at, `${context}.checked_at`),
        detail: nullableString(item.detail, `${context}.detail`),
    };
}

export function parseDashboardCapabilities(value: unknown): DashboardCapabilities {
    const response = record(value, 'dashboard_capabilities');
    return {
        status: dashboardStatus(response.status, 'dashboard_capabilities.status'),
        checkedAt: dateTime(response.checked_at, 'dashboard_capabilities.checked_at'),
        capabilities: array(response.capabilities, 'dashboard_capabilities.capabilities').map((item, index) => parseCapability(item, `dashboard_capabilities.capabilities[${index}]`)),
    };
}

async function request<T>(path: string, parse: (payload: unknown) => T): Promise<T> {
    const response = await fetch(path, {
        credentials: 'include',
        headers: { Accept: 'application/json' },
    });
    if (!response.ok) {
        let message = `Dashboard request failed (HTTP ${response.status}).`;
        try {
            const payload: unknown = await response.json();
            message = parseApiErrorMessage(payload) ?? message;
        } catch { /* HTTP status remains useful when the body is not JSON. */ }
        throw new DashboardApiError(message, response.status);
    }
    const payload: unknown = await response.json();
    return parse(payload);
}

export function getRecentAnalyses(query: RecentAnalysesQuery = {}): Promise<RecentAnalyses> {
    const params = new URLSearchParams({ limit: String(query.limit ?? 10) });
    if (query.next_cursor) params.set('next_cursor', query.next_cursor);
    return request(`/api/v1/dashboard/recent-analyses?${params.toString()}`, parseRecentAnalyses);
}

export function getMarketMovers(): Promise<MarketMovers> {
    return request('/api/v1/dashboard/market-movers?limit=3', parseMarketMovers);
}

export function getDashboardCapabilities(): Promise<DashboardCapabilities> {
    return request('/api/v1/dashboard/capabilities', parseDashboardCapabilities);
}
