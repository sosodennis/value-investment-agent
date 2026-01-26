import { AgentStatus } from './index';

export type IntentExtractionKind = 'success' | 'error';

export interface CompanyProfile {
    symbol: string;
    name: string;
    sector?: string;
    industry?: string;
    description?: string;
    [key: string]: any;
}

export interface IntentExtractionSuccess {
    kind: 'success';
    resolved_ticker: string;
    company_profile: CompanyProfile;
    status: 'resolved';
}

export interface IntentExtractionError {
    kind: 'error';
    message: string;
}

export type IntentExtractionResult = IntentExtractionSuccess | IntentExtractionError;
