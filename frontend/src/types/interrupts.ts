export interface TickerCandidate {
    symbol: string;
    name: string;
    exchange?: string;
    type?: string;
    confidence: number;
}

export interface IntentExtraction {
    company_name?: string;
    ticker?: string;
    model_preference?: string;
    is_valuation_request: boolean;
    reasoning: string;
}

export interface ApprovalDetails {
    ticker?: string;
    model?: string;
    audit_passed: boolean;
    audit_messages: string[];
}

export interface HumanApprovalRequest {
    type: 'approval_request';
    action: string;
    details: ApprovalDetails;
}

export interface HumanTickerSelection {
    type: 'ticker_selection';
    candidates: TickerCandidate[];
    intent?: IntentExtraction;
    reason: string;
}

export type Interrupt = HumanApprovalRequest | HumanTickerSelection;
