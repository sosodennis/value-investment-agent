import type { Capabilities, CapabilityStatus, MarketMovers, RecentAnalyses } from './home-models';

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requiredString(record: UnknownRecord, key: string, context: string): string {
    const value = record[key];
    if (typeof value !== 'string' || value.trim().length === 0) {
        throw new TypeError(`${context}.${key} must be a non-empty string.`);
    }
    return value;
}

function optionalString(record: UnknownRecord, key: string, context: string): string | undefined {
    const value = record[key];
    if (value === undefined) return undefined;
    if (typeof value !== 'string') throw new TypeError(`${context}.${key} must be a string.`);
    return value;
}

function requiredFiniteNumber(record: UnknownRecord, key: string, context: string): number {
    const value = record[key];
    if (typeof value !== 'number' || !Number.isFinite(value)) {
        throw new TypeError(`${context}.${key} must be a finite number.`);
    }
    return value;
}

function requiredArray(record: UnknownRecord, key: string, context: string): unknown[] {
    const value = record[key];
    if (!Array.isArray(value)) throw new TypeError(`${context}.${key} must be an array.`);
    return value;
}

function parseRecentAnalysis(value: unknown, context: string): RecentAnalyses['items'][number] {
    if (!isRecord(value)) throw new TypeError(`${context} must be an object.`);
    return {
        thread_id: requiredString(value, 'thread_id', context),
        run_id: requiredString(value, 'run_id', context),
        status: requiredString(value, 'status', context),
        started_at: requiredString(value, 'started_at', context),
        updated_at: requiredString(value, 'updated_at', context),
        ticker: optionalString(value, 'ticker', context),
        company_name: optionalString(value, 'company_name', context),
        summary: optionalString(value, 'summary', context),
    };
}

export function parseRecentAnalyses(value: unknown): RecentAnalyses {
    if (!isRecord(value)) throw new TypeError('recent_analyses must be an object.');
    const items = requiredArray(value, 'items', 'recent_analyses').map((item, index) =>
        parseRecentAnalysis(item, `recent_analyses.items[${index}]`)
    );
    const nextCursor = optionalString(value, 'next_cursor', 'recent_analyses');
    return nextCursor === undefined ? { items } : { items, next_cursor: nextCursor };
}

export function parseMarketMovers(value: unknown): MarketMovers {
    if (!isRecord(value)) throw new TypeError('market_movers must be an object.');
    const status = requiredString(value, 'status', 'market_movers');
    if (status !== 'fresh' && status !== 'stale' && status !== 'unavailable') {
        throw new TypeError('market_movers.status is invalid.');
    }
    const items = requiredArray(value, 'items', 'market_movers').map((item, index) => {
        const context = `market_movers.items[${index}]`;
        if (!isRecord(item)) throw new TypeError(`${context} must be an object.`);
        return {
            symbol: requiredString(item, 'symbol', context),
            name: requiredString(item, 'name', context),
            price: requiredFiniteNumber(item, 'price', context),
            change_absolute: requiredFiniteNumber(item, 'change_absolute', context),
            change_percent: requiredFiniteNumber(item, 'change_percent', context),
            currency: requiredString(item, 'currency', context),
            market_state: requiredString(item, 'market_state', context),
            quote_time: requiredString(item, 'quote_time', context),
        };
    });
    const errorCode = optionalString(value, 'error_code', 'market_movers');
    return {
        source: requiredString(value, 'source', 'market_movers'),
        as_of: requiredString(value, 'as_of', 'market_movers'),
        fetched_at: requiredString(value, 'fetched_at', 'market_movers'),
        status,
        items,
        ...(errorCode === undefined ? {} : { error_code: errorCode }),
    };
}

function parseCapabilityStatus(value: string): CapabilityStatus {
    if (value === 'operational' || value === 'degraded' || value === 'unavailable' || value === 'unknown') {
        return value;
    }
    throw new TypeError('capability.status is invalid.');
}

export function parseCapabilities(value: unknown): Capabilities {
    if (!isRecord(value)) throw new TypeError('capabilities must be an object.');
    const items = requiredArray(value, 'items', 'capabilities').map((item, index) => {
        const context = `capabilities.items[${index}]`;
        if (!isRecord(item)) throw new TypeError(`${context} must be an object.`);
        return {
            id: requiredString(item, 'id', context),
            label: requiredString(item, 'label', context),
            status: parseCapabilityStatus(requiredString(item, 'status', context)),
            source: requiredString(item, 'source', context),
            checked_at: requiredString(item, 'checked_at', context),
        };
    });
    return { checked_at: requiredString(value, 'checked_at', 'capabilities'), items };
}
