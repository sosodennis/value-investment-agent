export type RecentAnalysis = {
    thread_id: string;
    run_id: string;
    status: string;
    started_at: string;
    updated_at: string;
    ticker?: string;
    company_name?: string;
    summary?: string;
};

export type RecentAnalyses = {
    items: RecentAnalysis[];
    next_cursor?: string;
};

export type MarketMover = {
    symbol: string;
    name: string;
    price: number;
    change_absolute: number;
    change_percent: number;
    currency: string;
    market_state: string;
    quote_time: string;
};

export type MarketMovers = {
    source: string;
    as_of: string;
    fetched_at: string;
    status: 'fresh' | 'stale' | 'unavailable';
    items: MarketMover[];
    error_code?: string;
};

export type CapabilityStatus = 'operational' | 'degraded' | 'unavailable' | 'unknown';

export type Capability = {
    id: string;
    label: string;
    status: CapabilityStatus;
    source: string;
    checked_at: string;
};

export type Capabilities = {
    checked_at: string;
    items: Capability[];
};
