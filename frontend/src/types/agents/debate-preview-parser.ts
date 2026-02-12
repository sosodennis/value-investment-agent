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

    if (verdict !== undefined) preview.verdict_display = verdict;
    if (thesis !== undefined) preview.thesis_display = thesis;
    if (catalyst !== undefined) preview.catalyst_display = catalyst;
    if (risk !== undefined) preview.risk_display = risk;
    if (rounds !== undefined) preview.debate_rounds_display = rounds;
    return preview;
};
