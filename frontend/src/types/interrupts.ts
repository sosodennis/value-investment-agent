import { UnknownRecord, isRecord } from './preview';
import { RJSFSchema, UiSchema } from '@rjsf/utils';

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

export interface HumanTickerSelection {
    type: 'ticker_selection';
    candidates: TickerCandidate[];
    intent?: IntentExtraction;
    reason: string;
}

export type Interrupt = HumanTickerSelection;

export interface InterruptRequestData extends UnknownRecord {
    type: 'ticker_selection';
    title: string;
    description: string;
    data: Record<string, unknown>;
    schema: RJSFSchema;
    ui_schema?: UiSchema;
}

export interface TickerSelectionResumePayload {
    selected_symbol: string;
}

export interface AuditApprovalResumePayload {
    approved: boolean;
}

export type InterruptResumePayload =
    | TickerSelectionResumePayload
    | AuditApprovalResumePayload
    | Record<string, unknown>;

export const isInterruptRequestData = (
    value: unknown
): value is InterruptRequestData => {
    if (!isRecord(value)) return false;
    return (
        value.type === 'ticker_selection' &&
        typeof value.title === 'string' &&
        typeof value.description === 'string' &&
        isRecord(value.data) &&
        isRecord(value.schema)
    );
};
