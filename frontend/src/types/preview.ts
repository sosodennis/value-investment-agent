export type Primitive = string | number | boolean | null;
export type UnknownRecord = Record<string, unknown>;

export interface IntentPreview extends UnknownRecord {
    ticker?: string;
    company_name?: string;
    status_label?: string;
    exchange?: string;
}

export interface FundamentalPreview extends UnknownRecord {
    ticker?: string;
    company_name?: string;
    selected_model?: string;
    sector?: string;
    industry?: string;
    valuation_score?: number;
    status?: string;
    key_metrics?: Record<string, string>;
}

export interface NewsPreview extends UnknownRecord {
    status_label?: string;
    sentiment_display?: string;
    article_count_display?: string;
    top_headlines?: string[];
}

export interface TechnicalPreview extends UnknownRecord {
    ticker?: string;
    latest_price_display?: string;
    signal_display?: string;
    z_score_display?: string;
    optimal_d_display?: string;
    strength_display?: string;
}

export interface DebatePreview extends UnknownRecord {
    verdict_display?: string;
    thesis_display?: string;
    catalyst_display?: string;
    risk_display?: string;
    debate_rounds_display?: string;
}

export type PreviewPayload =
    | IntentPreview
    | FundamentalPreview
    | NewsPreview
    | TechnicalPreview
    | DebatePreview
    | UnknownRecord;

const hasStringField = (value: UnknownRecord, key: string): boolean =>
    typeof value[key] === 'string';

export const isRecord = (value: unknown): value is UnknownRecord =>
    typeof value === 'object' && value !== null;

export const isNewsPreview = (value: unknown): value is NewsPreview =>
    isRecord(value) && hasStringField(value, 'sentiment_display');

export const isDebatePreview = (value: unknown): value is DebatePreview =>
    isRecord(value) && hasStringField(value, 'verdict_display');

export const isTechnicalPreview = (value: unknown): value is TechnicalPreview =>
    isRecord(value) && hasStringField(value, 'signal_display');
