import type { components } from '@/types/generated/api-contract';
import { csrfHeaders } from '@/lib/auth-api';
import { isRecord } from '@/types/preview';
import type { FundamentalAutomaticPreparation } from '@/types/agents/fundamental-service-facts';

export type ForwardEvidenceResearchRequest =
    components['schemas']['ForwardEvidenceResearchRequest'];
export type ForwardEvidenceReview =
    components['schemas']['FundamentalForwardEvidenceReviewResultV1'];
export type ForwardEvidenceClaim =
    components['schemas']['FundamentalForwardEvidenceClaimV1'];

export type ForwardEvidenceManualOverride = {
    contract_version: 'fundamental.v1';
    preparation: FundamentalAutomaticPreparation;
    path: string;
    value: string;
    provenance: {
        author: string;
        modified_at: string;
        reason: string;
        automatic_preparation_digest: string;
        forward_reference: {
            claim_id: string;
            source_url: string;
            source_content_hash: string;
            citation: string;
            license_reference: string;
        };
    };
};

const parseRecord = (value: unknown, context: string): Record<string, unknown> => {
    if (!isRecord(value) || Array.isArray(value)) {
        throw new TypeError(`${context} must be an object.`);
    }
    return value;
};

const parseString = (value: unknown, context: string): string => {
    if (typeof value !== 'string' || value.length === 0) {
        throw new TypeError(`${context} must be a non-empty string.`);
    }
    return value;
};

const parseStringArray = (value: unknown, context: string): string[] => {
    if (!Array.isArray(value)) throw new TypeError(`${context} must be an array.`);
    return value.map((item, index) => parseString(item, `${context}[${index}]`));
};

const parseDigest = (value: unknown, context: string): string => {
    const parsed = parseString(value, context);
    if (!/^[0-9a-f]{64}$/.test(parsed)) {
        throw new TypeError(`${context} must be a lowercase SHA-256 digest.`);
    }
    return parsed;
};

const parseStatus = (value: unknown, context: string): ForwardEvidenceReview['status'] => {
    if (value === 'prepared' || value === 'unsupported' || value === 'unavailable') return value;
    throw new TypeError(`${context} must be a supported forward evidence status.`);
};

const parseSource = (
    value: unknown,
    context: string,
): ForwardEvidenceClaim['source'] => {
    const record = parseRecord(value, context);
    const sourceUrl = parseString(record.source_url, `${context}.source_url`);
    const parsedUrl = new URL(sourceUrl);
    if (parsedUrl.protocol !== 'http:' && parsedUrl.protocol !== 'https:') {
        throw new TypeError(`${context}.source_url must be an http or https URL.`);
    }
    const licenseStatus = record.license_status;
    if (licenseStatus !== 'approved' && licenseStatus !== 'unknown' && licenseStatus !== 'rejected') {
        throw new TypeError(`${context}.license_status must be approved, unknown, or rejected.`);
    }
    const sourceType = record.source_type;
    if (
        sourceType !== 'issuer_guidance' &&
        sourceType !== 'analyst_estimate' &&
        sourceType !== 'debt_terms' &&
        sourceType !== 'search_discovery'
    ) {
        throw new TypeError(`${context}.source_type is unsupported.`);
    }
    const licenseReference = record.license_reference;
    if (licenseReference !== undefined && licenseReference !== null && typeof licenseReference !== 'string') {
        throw new TypeError(`${context}.license_reference must be a string or null.`);
    }
    return {
        source_id: parseString(record.source_id, `${context}.source_id`),
        source_url: sourceUrl,
        publisher: parseString(record.publisher, `${context}.publisher`),
        source_type: sourceType,
        retained_passage: parseString(record.retained_passage, `${context}.retained_passage`),
        content_hash: parseDigest(record.content_hash, `${context}.content_hash`),
        published_at: parseString(record.published_at, `${context}.published_at`),
        retrieved_at: parseString(record.retrieved_at, `${context}.retrieved_at`),
        license_status: licenseStatus,
        license_reference: licenseReference ?? null,
    };
};

const parseClaim = (value: unknown, context: string): ForwardEvidenceClaim => {
    const record = parseRecord(value, context);
    const modelId = record.model_id;
    if (modelId !== 'fcff_dcf' && modelId !== 'transition_fcff_dcf') {
        throw new TypeError(`${context}.model_id is unsupported.`);
    }
    const metric = record.metric;
    if (
        metric !== 'revenue_growth' &&
        metric !== 'operating_margin' &&
        metric !== 'reinvestment_rate' &&
        metric !== 'debt_term'
    ) {
        throw new TypeError(`${context}.metric is unsupported.`);
    }
    const unit = record.unit;
    if (unit !== 'ratio' && unit !== 'currency' && unit !== 'days' && unit !== 'text') {
        throw new TypeError(`${context}.unit is unsupported.`);
    }
    const periodType = record.period_type;
    if (periodType !== 'annual' && periodType !== 'quarterly') {
        throw new TypeError(`${context}.period_type is unsupported.`);
    }
    const extractionMethod = record.extraction_method;
    if (extractionMethod !== 'structured_provider' && extractionMethod !== 'llm_from_source_passage') {
        throw new TypeError(`${context}.extraction_method is unsupported.`);
    }
    const status = record.status;
    if (status !== 'accepted' && status !== 'excluded') {
        throw new TypeError(`${context}.status is unsupported.`);
    }
    const assumptionPath = record.assumption_path;
    if (assumptionPath !== undefined && assumptionPath !== null && typeof assumptionPath !== 'string') {
        throw new TypeError(`${context}.assumption_path must be a string or null.`);
    }
    return {
        claim_id: parseString(record.claim_id, `${context}.claim_id`),
        issuer_id: parseString(record.issuer_id, `${context}.issuer_id`),
        ticker: parseString(record.ticker, `${context}.ticker`),
        model_id: modelId,
        metric,
        assumption_path: assumptionPath ?? null,
        value: parseString(record.value, `${context}.value`),
        unit,
        fiscal_period: parseString(record.fiscal_period, `${context}.fiscal_period`),
        period_type: periodType,
        period_end: parseString(record.period_end, `${context}.period_end`),
        extraction_method: extractionMethod,
        source: parseSource(record.source, `${context}.source`),
        status,
        issue_codes: parseStringArray(record.issue_codes ?? [], `${context}.issue_codes`),
        exclusion_reasons: parseStringArray(record.exclusion_reasons ?? [], `${context}.exclusion_reasons`),
    };
};

const parseBudget = (
    value: unknown,
    context: string,
): ForwardEvidenceReview['budget'] => {
    const record = parseRecord(value, context);
    return {
        policy_version: parseString(record.policy_version, `${context}.policy_version`),
        max_search_queries: Number(record.max_search_queries),
        max_results_per_query: Number(record.max_results_per_query),
        max_source_bytes: Number(record.max_source_bytes),
        max_llm_claims: Number(record.max_llm_claims),
        max_duration_ms: Number(record.max_duration_ms),
    };
};

const parseUsage = (
    value: unknown,
    context: string,
): ForwardEvidenceReview['usage'] => {
    const record = parseRecord(value, context);
    const llmOutputTokens = record.llm_output_tokens;
    if (llmOutputTokens !== undefined && llmOutputTokens !== null && typeof llmOutputTokens !== 'number') {
        throw new TypeError(`${context}.llm_output_tokens must be a number or null.`);
    }
    return {
        search_queries: Number(record.search_queries),
        search_results: Number(record.search_results),
        source_fetches: Number(record.source_fetches),
        llm_calls: Number(record.llm_calls),
        llm_input_bytes: Number(record.llm_input_bytes),
        llm_output_tokens: llmOutputTokens ?? null,
        elapsed_ms: Number(record.elapsed_ms),
    };
};

export function parseForwardEvidenceReview(value: unknown): ForwardEvidenceReview {
    const envelope = parseRecord(value, 'forward evidence response');
    const result = parseRecord(envelope.result, 'forward evidence response.result');
    if (result.contract_version !== 'fundamental.v1' || result.label !== 'forward-looking external evidence') {
        throw new TypeError('forward evidence response has an invalid contract identity.');
    }
    return {
        contract_version: 'fundamental.v1',
        status: parseStatus(result.status, 'forward evidence response.result.status'),
        label: 'forward-looking external evidence',
        policy_version: parseString(result.policy_version, 'forward evidence response.result.policy_version'),
        automatic_preparation_digest: parseDigest(
            result.automatic_preparation_digest,
            'forward evidence response.result.automatic_preparation_digest',
        ),
        claims: Array.isArray(result.claims)
            ? result.claims.map((claim, index) => parseClaim(claim, `forward evidence response.result.claims[${index}]`))
            : (() => { throw new TypeError('forward evidence response.result.claims must be an array.'); })(),
        accepted_claim_ids: parseStringArray(result.accepted_claim_ids ?? [], 'forward evidence response.result.accepted_claim_ids'),
        excluded_claim_ids: parseStringArray(result.excluded_claim_ids ?? [], 'forward evidence response.result.excluded_claim_ids'),
        issue_codes: parseStringArray(result.issue_codes ?? [], 'forward evidence response.result.issue_codes'),
        budget: parseBudget(result.budget, 'forward evidence response.result.budget'),
        usage: parseUsage(result.usage, 'forward evidence response.result.usage'),
        reference_digest: parseDigest(result.reference_digest, 'forward evidence response.result.reference_digest'),
    };
}

export async function researchForwardEvidence(
    request: ForwardEvidenceResearchRequest,
): Promise<ForwardEvidenceReview> {
    const response = await fetch('/api/v1/fundamental/forward-evidence/research', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...csrfHeaders() },
        body: JSON.stringify(request),
    });
    if (!response.ok) {
        throw new Error(`Forward evidence research failed (${response.status}).`);
    }
    return parseForwardEvidenceReview(await response.json());
}
