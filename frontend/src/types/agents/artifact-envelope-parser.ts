import { operations } from '@/types/generated/api-contract';
import { isRecord } from '../preview';

type ArtifactEnvelopeResponse =
    operations['get_artifact_api_artifacts__artifact_id__get']['responses'][200]['content']['application/json'];

export type ArtifactKind = ArtifactEnvelopeResponse['kind'];

const toRecord = (
    value: unknown,
    context: string
): Record<string, unknown> => {
    if (!isRecord(value) || Array.isArray(value)) {
        throw new TypeError(`${context} must be an object.`);
    }
    return value;
};

const parseArtifactKind = (value: unknown, context: string): ArtifactKind => {
    if (value === 'financial_reports') return value;
    if (value === 'price_series') return value;
    if (value === 'ta_chart_data') return value;
    if (value === 'ta_full_report') return value;
    if (value === 'search_results') return value;
    if (value === 'news_selection') return value;
    if (value === 'news_article') return value;
    if (value === 'news_items_list') return value;
    if (value === 'news_analysis_report') return value;
    if (value === 'debate_facts') return value;
    if (value === 'debate_final_report') return value;
    throw new TypeError(`${context}.kind has unsupported value.`);
};

export interface ParsedArtifactEnvelope {
    kind: ArtifactKind;
    version: 'v1';
    produced_by: string;
    created_at: string;
    data: unknown;
}

export const parseArtifactEnvelope = (
    value: unknown,
    context: string,
    expectedKind?: ArtifactKind
): ParsedArtifactEnvelope => {
    const record = toRecord(value, context);

    const kind = record.kind;
    const version = record.version;
    const producedBy = record.produced_by;
    const createdAt = record.created_at;

    const parsedKind = parseArtifactKind(kind, context);
    if (version !== 'v1') {
        throw new TypeError(`${context}.version must be "v1".`);
    }
    if (typeof producedBy !== 'string') {
        throw new TypeError(`${context}.produced_by must be a string.`);
    }
    if (typeof createdAt !== 'string') {
        throw new TypeError(`${context}.created_at must be a string.`);
    }
    if (!('data' in record)) {
        throw new TypeError(`${context}.data is required.`);
    }

    if (expectedKind && parsedKind !== expectedKind) {
        throw new TypeError(
            `${context}.kind must be ${expectedKind}, received ${parsedKind}.`
        );
    }

    return {
        kind: parsedKind,
        version,
        produced_by: producedBy,
        created_at: createdAt,
        data: record.data,
    };
};
