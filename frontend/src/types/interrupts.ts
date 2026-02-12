import { UnknownRecord, isRecord } from './preview';
import { RJSFSchema, UiSchema } from '@rjsf/utils';

export interface TickerCandidate {
    symbol: string;
    name: string;
    exchange?: string | null;
    type?: string | null;
    confidence: number;
}

export interface IntentExtraction {
    company_name?: string | null;
    ticker?: string | null;
    model_preference?: string | null;
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
    | AuditApprovalResumePayload;

export const parseInterruptResumePayload = (
    value: unknown
): InterruptResumePayload => {
    if (!isRecord(value)) {
        throw new TypeError('Interrupt resume payload must be an object.');
    }
    if (typeof value.selected_symbol === 'string') {
        return { selected_symbol: value.selected_symbol };
    }
    if (typeof value.approved === 'boolean') {
        return { approved: value.approved };
    }
    throw new TypeError(
        'Unsupported interrupt resume payload shape. Expected selected_symbol or approved.'
    );
};

export const isInterruptRequestData = (
    value: unknown
): value is InterruptRequestData => {
    if (!isRecord(value)) return false;
    if ('ui_schema' in value && value.ui_schema !== undefined && !isRecord(value.ui_schema)) {
        return false;
    }
    return (
        value.type === 'ticker_selection' &&
        typeof value.title === 'string' &&
        typeof value.description === 'string' &&
        isRecord(value.data) &&
        isRecord(value.schema)
    );
};

export const parseInterruptRequestData = (
    value: unknown,
    context = 'interrupt request'
): InterruptRequestData => {
    if (!isInterruptRequestData(value)) {
        throw new TypeError(
            `${context} has invalid shape. Expected ticker_selection interrupt payload.`
        );
    }
    return value;
};
