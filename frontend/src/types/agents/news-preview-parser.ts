import { isRecord, NewsPreview } from '../preview';

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

export const parseNewsPreview = (
    value: unknown,
    context = 'news preview'
): NewsPreview | null => {
    if (value === undefined || value === null) return null;
    const record = toRecord(value, context);

    const preview: NewsPreview = {};
    const statusLabel = parseOptionalString(
        record.status_label,
        `${context}.status_label`
    );
    const sentimentDisplay = parseOptionalString(
        record.sentiment_display,
        `${context}.sentiment_display`
    );
    const articleCountDisplay = parseOptionalString(
        record.article_count_display,
        `${context}.article_count_display`
    );

    if (statusLabel !== undefined) preview.status_label = statusLabel;
    if (sentimentDisplay !== undefined) preview.sentiment_display = sentimentDisplay;
    if (articleCountDisplay !== undefined) {
        preview.article_count_display = articleCountDisplay;
    }

    if ('top_headlines' in record) {
        const topHeadlines = record.top_headlines;
        if (
            !Array.isArray(topHeadlines) ||
            !topHeadlines.every((headline) => typeof headline === 'string')
        ) {
            throw new TypeError(
                `${context}.top_headlines must be an array of strings.`
            );
        }
        preview.top_headlines = topHeadlines;
    }

    return preview;
};
