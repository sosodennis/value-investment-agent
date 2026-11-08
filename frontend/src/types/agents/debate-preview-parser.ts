import { DebatePreview, isRecord } from '../preview';

const toRecord = (value: unknown, context: string): Record<string, unknown> => {
    if (!isRecord(value) || Array.isArray(value)) {
        throw new TypeError(`${context} must be an object.`);
    }
    return value;
};

const parseOptionalString = (
    value: unknown,
    context: string
): string | undefined => {
    if (value === undefined) return undefined;
    if (typeof value === 'string') return value;
    throw new TypeError(`${context} must be a string | undefined.`);
};

export const parseDebatePreview = (
    value: unknown,
    context = 'debate preview'
): DebatePreview | null => {
    if (value === undefined || value === null) return null;
    const record = toRecord(value, context);

    const preview: DebatePreview = {};
    const status = parseOptionalString(record.status, `${context}.status`);
    if (status !== undefined && !['completed', 'degraded', 'abstained'].includes(status)) {
        throw new TypeError(`${context}.status has unsupported value.`);
    }
    const statusLabel = parseOptionalString(record.status_label, `${context}.status_label`);
    const reason = parseOptionalString(record.reason_display, `${context}.reason_display`);
    let reasons: string[] | undefined;
    if (record.degraded_reasons !== undefined) {
        if (!Array.isArray(record.degraded_reasons) || !record.degraded_reasons.every((item) => typeof item === 'string')) {
            throw new TypeError(`${context}.degraded_reasons must be an array of strings.`);
        }
        reasons = record.degraded_reasons;
    }
    const verdict = parseOptionalString(
        record.verdict_display,
        `${context}.verdict_display`
    );
    const thesis = parseOptionalString(
        record.thesis_display,
        `${context}.thesis_display`
    );
    const catalyst = parseOptionalString(
        record.catalyst_display,
        `${context}.catalyst_display`
    );
    const risk = parseOptionalString(record.risk_display, `${context}.risk_display`);
    const rounds = parseOptionalString(
        record.debate_rounds_display,
        `${context}.debate_rounds_display`
    );

    if (status === 'completed' || status === 'degraded' || status === 'abstained') {
        preview.status = status;
    }
    if (statusLabel !== undefined) preview.status_label = statusLabel;
    if (reason !== undefined) preview.reason_display = reason;
    if (reasons !== undefined) preview.degraded_reasons = reasons;
    if (verdict !== undefined) preview.verdict_display = verdict;
    if (thesis !== undefined) preview.thesis_display = thesis;
    if (catalyst !== undefined) preview.catalyst_display = catalyst;
    if (risk !== undefined) preview.risk_display = risk;
    if (rounds !== undefined) preview.debate_rounds_display = rounds;
    return preview;
};
