export type SentimentLabel = 'bullish' | 'bearish' | 'neutral';
export type ImpactLevel = 'high' | 'medium' | 'low';

export type SearchCategory =
    | 'general'
    | 'corporate_event'
    | 'financials'
    | 'trusted_news'
    | 'analyst_opinion'
    | 'bullish'
    | 'bearish';

export interface SourceInfo {
    name: string;
    domain: string;
    reliability_score: number;
    author?: string | null;
}

export interface FinancialEntity {
    ticker: string;
    company_name: string;
    relevance_score: number;
}

export interface KeyFact {
    content: string;
    is_quantitative: boolean;
    sentiment: SentimentLabel;
    citation?: string | null;
}

export interface AIAnalysis {
    summary: string;
    sentiment: SentimentLabel;
    sentiment_score: number;
    impact_level: ImpactLevel;
    key_event?: string | null;
    reasoning: string;
    key_facts: KeyFact[];
}

export interface FinancialNewsItem {
    id: string;
    url: string;
    published_at?: string | null;
    fetched_at: string;
    title: string;
    snippet: string;
    full_content?: string | null;
    source: SourceInfo;
    related_tickers: FinancialEntity[];
    categories: SearchCategory[];
    tags: string[];
    analysis?: AIAnalysis | null;
}

export interface NewsResearchOutput {
    ticker: string;
    news_items: FinancialNewsItem[];
    overall_sentiment: SentimentLabel;
    sentiment_score: number;
    key_themes: string[];
}
