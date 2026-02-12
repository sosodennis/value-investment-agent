import { isRecord, TechnicalPreview } from '../preview';

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

const parseNullableOptionalString = (
    value: unknown,
    context: string
): string | undefined => {
    if (value === null) return undefined;
    return parseOptionalString(value, context);
};

export const parseTechnicalPreview = (
    value: unknown,
    context = 'technical preview'
): TechnicalPreview | null => {
    if (value === undefined || value === null) return null;
    const record = toRecord(value, context);

    const preview: TechnicalPreview = {};
    const ticker = parseNullableOptionalString(record.ticker, `${context}.ticker`);
    const latestPrice = parseOptionalString(
        record.latest_price_display,
        `${context}.latest_price_display`
    );
    const signal = parseOptionalString(
        record.signal_display,
        `${context}.signal_display`
    );
    const zScore = parseOptionalString(
        record.z_score_display,
        `${context}.z_score_display`
    );
    const optimalD = parseOptionalString(
        record.optimal_d_display,
        `${context}.optimal_d_display`
    );
    const strength = parseOptionalString(
        record.strength_display,
        `${context}.strength_display`
    );

    if (ticker !== undefined) preview.ticker = ticker;
    if (latestPrice !== undefined) preview.latest_price_display = latestPrice;
    if (signal !== undefined) preview.signal_display = signal;
    if (zScore !== undefined) preview.z_score_display = zScore;
    if (optimalD !== undefined) preview.optimal_d_display = optimalD;
    if (strength !== undefined) preview.strength_display = strength;
    return preview;
};
