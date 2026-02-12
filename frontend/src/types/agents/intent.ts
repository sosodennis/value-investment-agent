export interface CompanyProfile {
    symbol: string;
    name: string;
    sector?: string;
    industry?: string;
    description?: string;
    [key: string]: unknown;
}

export interface IntentExtractionSuccess {
    resolved_ticker: string;
    company_profile: CompanyProfile;
    status: 'resolved';
}

export interface IntentExtractionError {
    message: string;
}

export type IntentExtractionResult = IntentExtractionSuccess | IntentExtractionError;
