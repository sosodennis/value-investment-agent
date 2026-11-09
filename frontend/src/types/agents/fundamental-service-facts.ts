import { isRecord } from '../preview';

export type FundamentalQualityStatus =
    | 'verified'
    | 'provisional'
    | 'degraded'
    | 'unsupported'
    | 'abstain'
    | 'error';

export type FundamentalFamily = 'bank' | 'industrial' | 'reit';

export interface FundamentalIdentity {
    issuer_id: string;
    issuer_name: string;
    domicile: string;
    reporting_basis: 'us-gaap' | 'ifrs';
    security_id: string;
    share_class: string;
    currency: string;
    family?: FundamentalFamily;
}

export interface FundamentalDimension {
    name: string;
    member: string;
}

export interface FundamentalXbrlContext {
    concept_qname: string;
    period_type: 'instant' | 'duration';
    start_date?: string;
    end_date?: string;
    instant?: string;
    unit_qname: string;
    measure: string;
    dimensions: FundamentalDimension[];
    entity_scope: string;
    consolidation_scope: string;
    context_id: string;
}

export interface FundamentalFactPeriodInstant {
    kind: 'instant';
    end: string;
    instant: string;
}

export interface FundamentalFactPeriodDuration {
    kind: 'duration';
    start: string;
    end: string;
}

export type FundamentalFactPeriod =
    | FundamentalFactPeriodInstant
    | FundamentalFactPeriodDuration;

export interface FundamentalMissingValue {
    kind: 'missing';
    status: 'missing' | 'not_applicable' | 'unsupported' | 'unresolved';
    reason: string;
}

export interface FundamentalNumericValue {
    kind: 'numeric';
    /** Canonical service value in base units; `scale` remains source metadata. */
    raw: string;
    numeric: number;
}

export interface FundamentalTextValue {
    kind: 'text';
    value: string;
}

export interface FundamentalBooleanValue {
    kind: 'boolean';
    value: boolean;
}

export type FundamentalFactValue =
    | FundamentalNumericValue
    | FundamentalTextValue
    | FundamentalBooleanValue
    | FundamentalMissingValue;

export interface FundamentalFactProvenance {
    source_url: string;
    source_hash: string;
    source_role:
        | 'filing'
        | 'company_facts'
        | 'taxonomy'
        | 'acquisition'
        | 'macro'
        | 'market'
        | 'reference';
    captured_at: string;
    available_at: string;
    filed_at?: string;
    accession_number?: string;
    parser_version: string;
    taxonomy_version?: string;
    taxonomy_manifest_digest?: string;
    mapping_version?: string;
    terms_reference?: string;
}

export interface FundamentalCanonicalFact {
    contract_version: 'fundamental.v1';
    fact_id: string;
    issuer_id: string;
    security_id?: string;
    concept: string;
    normalized_field: string;
    value: FundamentalFactValue;
    unit: string;
    scale: number;
    currency?: string;
    period: FundamentalFactPeriod;
    context: FundamentalXbrlContext;
    security_scope?: string;
    as_of: string;
    available_at: string;
    filed_at?: string;
    captured_at: string;
    accession_number?: string;
    filing_version?: string;
    is_amendment: boolean;
    amends_accession?: string;
    supersedes_accession?: string;
    amendment_scope?: 'valuation_relevant' | 'unrelated' | 'unknown';
    decimals?: number;
    taxonomy_version: string;
    source: FundamentalFactProvenance;
    quality: FundamentalQualityStatus;
    issue_codes: string[];
    mapping_decision_id?: string;
    mapping_confidence?: 'high' | 'medium' | 'low' | 'unresolved';
    rejected_candidates: string[];
    point_in_time_policy?: string;
    selection_reason?: string;
    family?: FundamentalFamily;
}

export interface FundamentalFactsReadResult {
    contract_version: 'fundamental.v1';
    snapshot_id: string;
    data_release_manifest_digest?: string;
    snapshot_manifest_digest: string;
    identity: FundamentalIdentity;
    valuation_timestamp: string;
    quality_status: FundamentalQualityStatus;
    issue_codes: string[];
    facts: FundamentalCanonicalFact[];
}

export interface FundamentalValuationTrace {
    source_selection_policy: string;
    source_selection_policy_version: string;
    snapshot_id: string;
    snapshot_manifest_digest: string;
    fact_ids: string[];
    source_content_hashes: string[];
    policy_id: string;
    policy_version: string;
    policy_digest: string;
    model_id: string;
    model_version: string;
    assumptions_digest: string;
    calculation_version: string;
}

export interface FundamentalArtifactProvenance {
    snapshot_id?: string;
    fact_ids?: string[];
    mapping_version?: string;
    parser_version?: string;
    taxonomy_version?: string;
    policy_version?: string;
}

export interface FundamentalArtifactQuality {
    input_status?: FundamentalQualityStatus;
    validation_status?: FundamentalQualityStatus;
    facts_status?: FundamentalQualityStatus;
    calculation_status?: FundamentalQualityStatus;
    issue_codes: string[];
}

export interface FundamentalArtifactHashes {
    input_digest: string;
    result_hash: string;
    snapshot_manifest_digest: string;
    data_release_manifest_digest?: string;
    source_content_hashes: string[];
}

export type FundamentalAssumptionMethod =
    | 'derived'
    | 'approved_source'
    | 'approved_policy'
    | 'manual';

export interface FundamentalManualProvenance {
    author: string;
    modified_at: string;
    reason: string;
    automatic_preparation_digest: string;
}

export interface FundamentalAssumptionEvidence {
    path: string;
    value: string | number;
    method: FundamentalAssumptionMethod;
    formula: string;
    fact_ids: string[];
    source_refs: string[];
    policy_version: string;
    as_of: string;
    editable: boolean;
    manual_provenance?: FundamentalManualProvenance;
}

export interface FundamentalAutomaticPreparation {
    contract_version: 'fundamental.v1';
    status: 'prepared' | 'requires_input' | 'abstained' | 'unsupported';
    model_id: string;
    model_version: string;
    profile_id: string;
    profile_digest: string;
    policy_id: string;
    policy_version: string;
    quality_status: FundamentalQualityStatus;
    issue_codes: string[];
    missing_evidence: string[];
    historical_metrics: Record<string, unknown>;
    assumptions_evidence: FundamentalAssumptionEvidence[];
    input: Record<string, unknown> | null;
    preparation_digest: string;
}

export interface FundamentalServiceValuationArtifact {
    projection_type: 'valuation';
    contract_version: 'fundamental.v1';
    snapshot_id: string;
    snapshot_manifest_digest: string;
    fact_ids: string[];
    facts: FundamentalFactsReadResult;
    valuation_trace: FundamentalValuationTrace;
    provenance: FundamentalArtifactProvenance;
    quality: FundamentalArtifactQuality;
    hashes: FundamentalArtifactHashes;
    model_id?: string;
    model_version?: string;
    calculation_version?: string;
    calculation_status?: string;
    quality_status?: FundamentalQualityStatus;
    input_digest?: string;
    result_hash?: string;
    intrinsic_value?: number;
    per_share_value?: number;
    evaluated_at?: string;
    issue_codes: string[];
    missing_evidence: string[];
    automatic_preparation?: FundamentalAutomaticPreparation;
    valuation_input?: Record<string, unknown>;
}

export interface FundamentalFactsOnlyArtifactQuality {
    facts_status: FundamentalQualityStatus;
    issue_codes: string[];
}

export interface FundamentalFactsOnlyArtifactHashes {
    snapshot_manifest_digest: string;
    data_release_manifest_digest?: string;
    source_content_hashes: string[];
}

export interface FundamentalServiceFactsOnlyArtifact {
    projection_type: 'facts_only';
    valuation_status: 'not_requested';
    contract_version: 'fundamental.v1';
    snapshot_id: string;
    snapshot_manifest_digest: string;
    fact_ids: string[];
    facts: FundamentalFactsReadResult;
    provenance: FundamentalArtifactProvenance;
    quality: FundamentalFactsOnlyArtifactQuality;
    hashes: FundamentalFactsOnlyArtifactHashes;
    issue_codes: string[];
}

export interface FundamentalServiceDegradedArtifact {
    projection_type: 'degraded';
    contract_version: 'fundamental.v1';
    valuation_status: 'service_unavailable';
    quality_status: 'degraded';
    issue_codes: string[];
    service_failure: {
        code: string;
        message: string;
        retryable: boolean;
    };
}

export type FundamentalServiceArtifact =
    | FundamentalServiceValuationArtifact
    | FundamentalServiceFactsOnlyArtifact
    | FundamentalServiceDegradedArtifact;

const DIGEST_PATTERN = /^[0-9a-f]{64}$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

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

const parseBoolean = (value: unknown, context: string): boolean => {
    if (typeof value !== 'boolean') {
        throw new TypeError(`${context} must be a boolean.`);
    }
    return value;
};

const parseOptionalString = (value: unknown, context: string): string | undefined => {
    if (value === undefined || value === null) return undefined;
    return parseString(value, context);
};

const parseValue = (value: unknown, context: string): string | number => {
    if (typeof value === 'string' && value.length > 0) return value;
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    throw new TypeError(`${context} must be a finite number or non-empty string.`);
};

const parseAssumptionMethod = (
    value: unknown,
    context: string
): FundamentalAssumptionMethod => {
    if (
        value !== 'derived' &&
        value !== 'approved_source' &&
        value !== 'approved_policy' &&
        value !== 'manual'
    ) {
        throw new TypeError(`${context} must be a supported assumption method.`);
    }
    return value;
};

const parseAutomaticPreparationStatus = (
    value: unknown,
    context: string
): FundamentalAutomaticPreparation['status'] => {
    if (
        value !== 'prepared' &&
        value !== 'requires_input' &&
        value !== 'abstained' &&
        value !== 'unsupported'
    ) {
        throw new TypeError(`${context} must be a supported preparation status.`);
    }
    return value;
};

const parseManualProvenance = (
    value: unknown,
    context: string
): FundamentalManualProvenance => {
    const record = parseRecord(value, context);
    return {
        author: parseString(record.author, `${context}.author`),
        modified_at: parseTimestamp(record.modified_at, `${context}.modified_at`),
        reason: parseString(record.reason, `${context}.reason`),
        automatic_preparation_digest: parseDigest(
            record.automatic_preparation_digest,
            `${context}.automatic_preparation_digest`
        ),
    };
};

const parseAssumptionEvidence = (
    value: unknown,
    context: string
): FundamentalAssumptionEvidence => {
    const record = parseRecord(value, context);
    const method = parseAssumptionMethod(record.method, `${context}.method`);
    const manualProvenance =
        record.manual_provenance === undefined || record.manual_provenance === null
            ? undefined
            : parseManualProvenance(record.manual_provenance, `${context}.manual_provenance`);
    if (method === 'manual' && manualProvenance === undefined) {
        throw new TypeError(`${context}.manual_provenance is required for manual evidence.`);
    }
    if (method !== 'manual' && manualProvenance !== undefined) {
        throw new TypeError(`${context}.manual_provenance is only valid for manual evidence.`);
    }
    const parsed: FundamentalAssumptionEvidence = {
        path: parseString(record.path, `${context}.path`),
        value: parseValue(record.value, `${context}.value`),
        method,
        formula: parseString(record.formula, `${context}.formula`),
        fact_ids: parseStringArray(record.fact_ids ?? [], `${context}.fact_ids`),
        source_refs: parseStringArray(record.source_refs ?? [], `${context}.source_refs`),
        policy_version: parseString(record.policy_version, `${context}.policy_version`),
        as_of: parseTimestamp(record.as_of, `${context}.as_of`),
        editable: record.editable === undefined ? true : parseBoolean(record.editable, `${context}.editable`),
    };
    if (manualProvenance !== undefined) parsed.manual_provenance = manualProvenance;
    return parsed;
};

const parseAutomaticPreparation = (
    value: unknown,
    context: string
): FundamentalAutomaticPreparation => {
    const record = parseRecord(value, context);
    const input =
        record.input === undefined || record.input === null
            ? null
            : parseRecord(record.input, `${context}.input`);
    const evidenceRaw = record.assumptions_evidence;
    if (!Array.isArray(evidenceRaw)) {
        throw new TypeError(`${context}.assumptions_evidence must be an array.`);
    }
    return {
        contract_version: 'fundamental.v1',
        status: parseAutomaticPreparationStatus(record.status, `${context}.status`),
        model_id: parseString(record.model_id, `${context}.model_id`),
        model_version: parseString(record.model_version, `${context}.model_version`),
        profile_id: parseString(record.profile_id, `${context}.profile_id`),
        profile_digest: parseDigest(record.profile_digest, `${context}.profile_digest`),
        policy_id: parseString(record.policy_id, `${context}.policy_id`),
        policy_version: parseString(record.policy_version, `${context}.policy_version`),
        quality_status: parseQuality(
            parseString(record.quality_status, `${context}.quality_status`),
            `${context}.quality_status`
        ),
        issue_codes: parseStringArray(record.issue_codes ?? [], `${context}.issue_codes`),
        missing_evidence: parseStringArray(record.missing_evidence ?? [], `${context}.missing_evidence`),
        historical_metrics: parseRecord(record.historical_metrics, `${context}.historical_metrics`),
        assumptions_evidence: evidenceRaw.map((item, index) =>
            parseAssumptionEvidence(item, `${context}.assumptions_evidence[${index}]`)
        ),
        input,
        preparation_digest: parseDigest(record.preparation_digest, `${context}.preparation_digest`),
    };
};

export const parseFundamentalAutomaticPreparation = (
    value: unknown,
    context = 'fundamental.automatic_preparation'
): FundamentalAutomaticPreparation => parseAutomaticPreparation(value, context);

const parseDate = (value: unknown, context: string): string => {
    const parsed = parseString(value, context);
    if (!DATE_PATTERN.test(parsed)) {
        throw new TypeError(`${context} must be an ISO date.`);
    }
    return parsed;
};

const parseTimestamp = (value: unknown, context: string): string => {
    const parsed = parseString(value, context);
    if (Number.isNaN(Date.parse(parsed))) {
        throw new TypeError(`${context} must be an ISO timestamp.`);
    }
    return parsed;
};

const parseDigest = (value: unknown, context: string): string => {
    const parsed = parseString(value, context);
    if (!DIGEST_PATTERN.test(parsed)) {
        throw new TypeError(`${context} must be a lowercase SHA-256 digest.`);
    }
    return parsed;
};

const parseQuality = (value: unknown, context: string): FundamentalQualityStatus => {
    if (typeof value !== 'string') {
        throw new TypeError(`${context} must be a supported quality status.`);
    }
    switch (value) {
        case 'verified':
        case 'provisional':
        case 'degraded':
        case 'unsupported':
        case 'abstain':
        case 'error':
            return value;
        default:
            throw new TypeError(`${context} must be a supported quality status.`);
    }
};

const parseFamily = (value: unknown, context: string): FundamentalFamily | undefined => {
    if (value === undefined || value === null) return undefined;
    if (typeof value !== 'string') {
        throw new TypeError(`${context} must be bank | industrial | reit.`);
    }
    switch (value) {
        case 'bank':
        case 'industrial':
        case 'reit':
            return value;
        default:
            throw new TypeError(`${context} must be bank | industrial | reit.`);
    }
};

const parseStringArray = (value: unknown, context: string): string[] => {
    if (value === undefined || value === null) return [];
    if (!Array.isArray(value)) throw new TypeError(`${context} must be an array.`);
    return value.map((item, index) => parseString(item, `${context}[${index}]`));
};

const parseRequiredDigestArray = (value: unknown, context: string): string[] => {
    if (!Array.isArray(value) || value.length === 0) {
        throw new TypeError(`${context} must be a non-empty digest array.`);
    }
    return value.map((item, index) => parseDigest(item, `${context}[${index}]`));
};

const parseOptionalNumber = (value: unknown, context: string): number | undefined => {
    if (value === undefined || value === null) return undefined;
    if (typeof value !== 'number' || !Number.isFinite(value)) {
        throw new TypeError(`${context} must be a finite number.`);
    }
    return value;
};

const parseDimensions = (value: unknown, context: string): FundamentalDimension[] => {
    if (value === undefined || value === null) return [];
    if (!Array.isArray(value)) throw new TypeError(`${context} must be an array.`);
    return value.map((entry, index) => {
        const record = parseRecord(entry, `${context}[${index}]`);
        return {
            name: parseString(record.name, `${context}[${index}].name`),
            member: parseString(record.member, `${context}[${index}].member`),
        };
    });
};

const parseContext = (value: unknown, context: string): FundamentalXbrlContext => {
    const record = parseRecord(value, context);
    const periodType = record.period_type;
    if (periodType !== 'instant' && periodType !== 'duration') {
        throw new TypeError(`${context}.period_type must be instant | duration.`);
    }
    const parsed: FundamentalXbrlContext = {
        concept_qname: parseString(record.concept_qname, `${context}.concept_qname`),
        period_type: periodType,
        unit_qname: parseString(record.unit_qname, `${context}.unit_qname`),
        measure: parseString(record.measure, `${context}.measure`),
        dimensions: parseDimensions(record.dimensions, `${context}.dimensions`),
        entity_scope: parseString(record.entity_scope, `${context}.entity_scope`),
        consolidation_scope: parseString(
            record.consolidation_scope,
            `${context}.consolidation_scope`
        ),
        context_id: parseString(record.context_id, `${context}.context_id`),
    };
    const startDate = record.start_date;
    const endDate = record.end_date;
    const instant = record.instant;
    if (startDate !== undefined && startDate !== null) {
        parsed.start_date = parseDate(startDate, `${context}.start_date`);
    }
    if (endDate !== undefined && endDate !== null) {
        parsed.end_date = parseDate(endDate, `${context}.end_date`);
    }
    if (instant !== undefined && instant !== null) {
        parsed.instant = parseDate(instant, `${context}.instant`);
    }
    if (periodType === 'instant' && !parsed.instant) {
        throw new TypeError(`${context}.instant is required for instant facts.`);
    }
    if (periodType === 'duration' && (!parsed.start_date || !parsed.end_date)) {
        throw new TypeError(`${context}.start_date and end_date are required for duration facts.`);
    }
    return parsed;
};

const parseFactValue = (value: unknown, context: string): FundamentalFactValue => {
    if (isRecord(value) && 'status' in value) {
        const status = value.status;
        if (
            status !== 'missing' &&
            status !== 'not_applicable' &&
            status !== 'unsupported' &&
            status !== 'unresolved'
        ) {
            throw new TypeError(`${context}.status is not a supported missing status.`);
        }
        return {
            kind: 'missing',
            status,
            reason: parseString(value.reason, `${context}.reason`),
        };
    }
    if (typeof value === 'boolean') return { kind: 'boolean', value };
    if (typeof value === 'number') {
        if (!Number.isFinite(value)) throw new TypeError(`${context} must be finite.`);
        return { kind: 'numeric', raw: String(value), numeric: value };
    }
    if (typeof value === 'string') {
        const numeric = Number(value);
        if (value.trim() !== '' && Number.isFinite(numeric)) {
            return { kind: 'numeric', raw: value, numeric };
        }
        return { kind: 'text', value };
    }
    throw new TypeError(`${context} must be a number, string, boolean, or missing value.`);
};

const parsePeriod = (
    record: Record<string, unknown>,
    xbrlContext: FundamentalXbrlContext,
    context: string
): FundamentalFactPeriod => {
    const periodEnd = parseDate(record.period_end, `${context}.period_end`);
    if (xbrlContext.period_type === 'instant') {
        const instant = record.instant ?? xbrlContext.instant;
        if (instant === undefined || instant === null) {
            throw new TypeError(`${context}.instant is required for instant facts.`);
        }
        const parsedInstant = parseDate(instant, `${context}.instant`);
        return { kind: 'instant', end: periodEnd, instant: parsedInstant };
    }
    const start = record.period_start ?? xbrlContext.start_date;
    if (start === undefined || start === null) {
        throw new TypeError(`${context}.period_start is required for duration facts.`);
    }
    return {
        kind: 'duration',
        start: parseDate(start, `${context}.period_start`),
        end: periodEnd,
    };
};

const parseProvenance = (
    value: unknown,
    fallback: Record<string, unknown>,
    context: string
): FundamentalFactProvenance => {
    const record = parseRecord(value, context);
    const contentHash = record.content_hash ?? record.source_hash ?? fallback.content_hash;
    const provenance: FundamentalFactProvenance = {
        source_url: parseString(record.source_url, `${context}.source_url`),
        source_hash: parseDigest(contentHash, `${context}.content_hash`),
        source_role: (() => {
            const role = parseString(record.source_role, `${context}.source_role`);
            if (
                role !== 'filing' &&
                role !== 'company_facts' &&
                role !== 'taxonomy' &&
                role !== 'acquisition' &&
                role !== 'macro' &&
                role !== 'market' &&
                role !== 'reference'
            ) {
                throw new TypeError(`${context}.source_role is unsupported.`);
            }
            return role;
        })(),
        captured_at: parseTimestamp(record.captured_at, `${context}.captured_at`),
        available_at: parseTimestamp(record.available_at, `${context}.available_at`),
        parser_version: parseString(record.parser_version, `${context}.parser_version`),
    };
    const optionalFields: Array<['filed_at' | 'accession_number' | 'taxonomy_version' | 'taxonomy_manifest_digest' | 'mapping_version' | 'terms_reference', string]> = [
        ['filed_at', 'filed_at'],
        ['accession_number', 'accession_number'],
        ['taxonomy_version', 'taxonomy_version'],
        ['taxonomy_manifest_digest', 'taxonomy_manifest_digest'],
        ['mapping_version', 'mapping_version'],
        ['terms_reference', 'terms_reference'],
    ];
    for (const [field, rawField] of optionalFields) {
        const parsed = parseOptionalString(record[rawField], `${context}.${rawField}`);
        if (parsed !== undefined) {
            if (field === 'taxonomy_manifest_digest') {
                provenance[field] = parseDigest(parsed, `${context}.${rawField}`);
            } else if (field === 'filed_at') {
                provenance[field] = parseTimestamp(parsed, `${context}.${rawField}`);
            } else {
                provenance[field] = parsed;
            }
        }
    }
    return provenance;
};

const parseIdentity = (value: unknown, context: string): FundamentalIdentity => {
    const record = parseRecord(value, context);
    const family = parseFamily(record.family ?? record.industry_family, `${context}.family`);
    return {
        issuer_id: parseString(record.issuer_id, `${context}.issuer_id`),
        issuer_name: parseString(record.issuer_name, `${context}.issuer_name`),
        domicile: parseString(record.domicile, `${context}.domicile`),
        reporting_basis: (() => {
            const basis = parseString(record.reporting_basis, `${context}.reporting_basis`);
            if (basis !== 'us-gaap' && basis !== 'ifrs') {
                throw new TypeError(`${context}.reporting_basis must be us-gaap | ifrs.`);
            }
            return basis;
        })(),
        security_id: parseString(record.security_id, `${context}.security_id`),
        share_class: parseString(record.share_class, `${context}.share_class`),
        currency: parseString(record.currency, `${context}.currency`),
        ...(family ? { family } : {}),
    };
};

const parseFact = (value: unknown, context: string): FundamentalCanonicalFact => {
    const record = parseRecord(value, context);
    if (record.contract_version !== 'fundamental.v1') {
        throw new TypeError(`${context}.contract_version must be fundamental.v1.`);
    }
    const xbrlContext = parseContext(record.context, `${context}.context`);
    const source = parseProvenance(record.source, record, `${context}.source`);
    const family = parseFamily(record.family ?? record.industry_family, `${context}.family`);
    const parsed: FundamentalCanonicalFact = {
        contract_version: 'fundamental.v1',
        fact_id: parseString(record.fact_id, `${context}.fact_id`),
        issuer_id: parseString(record.issuer_id, `${context}.issuer_id`),
        concept: parseString(record.concept, `${context}.concept`),
        normalized_field: parseString(record.normalized_field, `${context}.normalized_field`),
        value: parseFactValue(record.value, `${context}.value`),
        unit: parseString(record.unit, `${context}.unit`),
        scale: (() => {
            const scale = record.scale;
            if (typeof scale !== 'number' || !Number.isInteger(scale)) {
                throw new TypeError(`${context}.scale must be an integer.`);
            }
            return scale;
        })(),
        period: parsePeriod(record, xbrlContext, context),
        context: xbrlContext,
        as_of: parseTimestamp(record.as_of, `${context}.as_of`),
        available_at: parseTimestamp(record.available_at, `${context}.available_at`),
        captured_at: parseTimestamp(record.captured_at, `${context}.captured_at`),
        taxonomy_version: parseString(record.taxonomy_version, `${context}.taxonomy_version`),
        source,
        quality: parseQuality(record.quality, `${context}.quality`),
        issue_codes: parseStringArray(record.issue_codes, `${context}.issue_codes`),
        rejected_candidates: parseStringArray(
            record.rejected_candidates,
            `${context}.rejected_candidates`
        ),
        is_amendment: (() => {
            if (record.is_amendment === undefined) return false;
            if (typeof record.is_amendment !== 'boolean') {
                throw new TypeError(`${context}.is_amendment must be boolean.`);
            }
            return record.is_amendment;
        })(),
    };
    const optionalStringFields: Array<keyof Pick<FundamentalCanonicalFact, 'security_id' | 'currency' | 'filed_at' | 'accession_number' | 'filing_version' | 'amends_accession' | 'supersedes_accession' | 'point_in_time_policy' | 'selection_reason' | 'mapping_decision_id'>> = [
        'security_id',
        'currency',
        'filed_at',
        'accession_number',
        'filing_version',
        'amends_accession',
        'supersedes_accession',
        'point_in_time_policy',
        'selection_reason',
        'mapping_decision_id',
    ];
    for (const field of optionalStringFields) {
        const parsedValue = parseOptionalString(record[field], `${context}.${field}`);
        if (parsedValue !== undefined) {
            if (field === 'filed_at') {
                parsed[field] = parseTimestamp(parsedValue, `${context}.${field}`);
            } else {
                parsed[field] = parsedValue;
            }
        }
    }
    const decimals = parseOptionalNumber(record.decimals, `${context}.decimals`);
    if (decimals !== undefined) parsed.decimals = decimals;
    const mappingConfidence = parseOptionalString(
        record.mapping_confidence,
        `${context}.mapping_confidence`
    );
    if (mappingConfidence !== undefined) {
        switch (mappingConfidence) {
            case 'high':
                parsed.mapping_confidence = 'high';
                break;
            case 'medium':
                parsed.mapping_confidence = 'medium';
                break;
            case 'low':
                parsed.mapping_confidence = 'low';
                break;
            case 'unresolved':
                parsed.mapping_confidence = 'unresolved';
                break;
            default:
                throw new TypeError(`${context}.mapping_confidence is unsupported.`);
        }
    }
    const amendmentScope = parseOptionalString(record.amendment_scope, `${context}.amendment_scope`);
    if (amendmentScope !== undefined) {
        switch (amendmentScope) {
            case 'valuation_relevant':
                parsed.amendment_scope = 'valuation_relevant';
                break;
            case 'unrelated':
                parsed.amendment_scope = 'unrelated';
                break;
            case 'unknown':
                parsed.amendment_scope = 'unknown';
                break;
            default:
                throw new TypeError(`${context}.amendment_scope is unsupported.`);
        }
    }
    if (family !== undefined) parsed.family = family;
    return parsed;
};

export const sortFundamentalFacts = (
    facts: readonly FundamentalCanonicalFact[]
): FundamentalCanonicalFact[] => {
    return [...facts].sort((left, right) => {
        const end = right.period.end.localeCompare(left.period.end);
        if (end !== 0) return end;
        const leftStart = left.period.kind === 'duration' ? left.period.start : left.period.instant;
        const rightStart = right.period.kind === 'duration' ? right.period.start : right.period.instant;
        const start = rightStart.localeCompare(leftStart);
        if (start !== 0) return start;
        const kind = left.period.kind.localeCompare(right.period.kind);
        if (kind !== 0) return kind;
        return left.fact_id.localeCompare(right.fact_id);
    });
};

export const parseFundamentalFacts = (
    value: unknown,
    context = 'fundamental_service'
): FundamentalFactsReadResult => {
    const record = parseRecord(value, context);
    if (record.contract_version !== 'fundamental.v1') {
        throw new TypeError(`${context}.contract_version must be fundamental.v1.`);
    }
    if (!Array.isArray(record.facts) || record.facts.length === 0) {
        throw new TypeError(`${context}.facts must contain at least one fact.`);
    }
    const dataReleaseDigest = record.data_release_manifest_digest;
    const parsedDataReleaseDigest =
        dataReleaseDigest === undefined || dataReleaseDigest === null
            ? undefined
            : parseDigest(dataReleaseDigest, `${context}.data_release_manifest_digest`);
    const parsed: FundamentalFactsReadResult = {
        contract_version: 'fundamental.v1',
        snapshot_id: parseString(record.snapshot_id, `${context}.snapshot_id`),
        snapshot_manifest_digest: parseDigest(
            record.snapshot_manifest_digest,
            `${context}.snapshot_manifest_digest`
        ),
        identity: parseIdentity(record.identity, `${context}.identity`),
        valuation_timestamp: parseTimestamp(
            record.valuation_timestamp,
            `${context}.valuation_timestamp`
        ),
        quality_status: parseQuality(record.quality_status, `${context}.quality_status`),
        issue_codes: parseStringArray(record.issue_codes, `${context}.issue_codes`),
        facts: record.facts.map((fact, index) => parseFact(fact, `${context}.facts[${index}]`)),
    };
    if (parsedDataReleaseDigest !== undefined) {
        parsed.data_release_manifest_digest = parsedDataReleaseDigest;
    }
    const factIds = new Set<string>();
    for (const fact of parsed.facts) {
        if (factIds.has(fact.fact_id)) {
            throw new TypeError(`${context}.facts contains duplicate fact_id ${fact.fact_id}.`);
        }
        factIds.add(fact.fact_id);
    }
    return { ...parsed, facts: sortFundamentalFacts(parsed.facts) };
};

const parseProvenanceMetadata = (
    value: unknown,
    context: string
): FundamentalArtifactProvenance => {
    const record = parseRecord(value, context);
    const parsed: FundamentalArtifactProvenance = {};
    const snapshotId = parseOptionalString(record.snapshot_id, `${context}.snapshot_id`);
    if (snapshotId !== undefined) parsed.snapshot_id = snapshotId;
    const mappingVersion = parseOptionalString(record.mapping_version, `${context}.mapping_version`);
    if (mappingVersion !== undefined) parsed.mapping_version = mappingVersion;
    const parserVersion = parseOptionalString(record.parser_version, `${context}.parser_version`);
    if (parserVersion !== undefined) parsed.parser_version = parserVersion;
    const taxonomyVersion = parseOptionalString(record.taxonomy_version, `${context}.taxonomy_version`);
    if (taxonomyVersion !== undefined) parsed.taxonomy_version = taxonomyVersion;
    const policyVersion = parseOptionalString(record.policy_version, `${context}.policy_version`);
    if (policyVersion !== undefined) parsed.policy_version = policyVersion;
    if (record.fact_ids !== undefined && record.fact_ids !== null) {
        parsed.fact_ids = parseStringArray(record.fact_ids, `${context}.fact_ids`);
    }
    return parsed;
};

const parseQualityMetadata = (
    value: unknown,
    context: string
): FundamentalArtifactQuality => {
    const record = parseRecord(value, context);
    const parsed: FundamentalArtifactQuality = {
        issue_codes: parseStringArray(record.issue_codes, `${context}.issue_codes`),
    };
    const input = record.input;
    if (input !== undefined && input !== null) {
        const inputRecord = parseRecord(input, `${context}.input`);
        const inputStatus = parseOptionalString(inputRecord.status, `${context}.input.status`);
        if (inputStatus !== undefined) parsed.input_status = parseQuality(inputStatus, `${context}.input.status`);
    }
    const validationStatus = parseOptionalString(record.validation_status, `${context}.validation_status`);
    if (validationStatus !== undefined) parsed.validation_status = parseQuality(validationStatus, `${context}.validation_status`);
    const factsStatus = parseOptionalString(record.facts_status, `${context}.facts_status`);
    if (factsStatus !== undefined) parsed.facts_status = parseQuality(factsStatus, `${context}.facts_status`);
    const calculationStatus = parseOptionalString(record.calculation_status, `${context}.calculation_status`);
    if (calculationStatus !== undefined) parsed.calculation_status = parseQuality(calculationStatus, `${context}.calculation_status`);
    return parsed;
};

const parseValuationTrace = (
    value: unknown,
    context: string
): FundamentalValuationTrace => {
    const record = parseRecord(value, context);
    return {
        source_selection_policy: parseString(record.source_selection_policy, `${context}.source_selection_policy`),
        source_selection_policy_version: parseString(record.source_selection_policy_version, `${context}.source_selection_policy_version`),
        snapshot_id: parseString(record.snapshot_id, `${context}.snapshot_id`),
        snapshot_manifest_digest: parseDigest(record.snapshot_manifest_digest, `${context}.snapshot_manifest_digest`),
        fact_ids: parseStringArray(record.fact_ids, `${context}.fact_ids`),
        source_content_hashes: parseRequiredDigestArray(record.source_content_hashes, `${context}.source_content_hashes`),
        policy_id: parseString(record.policy_id, `${context}.policy_id`),
        policy_version: parseString(record.policy_version, `${context}.policy_version`),
        policy_digest: parseDigest(record.policy_digest, `${context}.policy_digest`),
        model_id: parseString(record.model_id, `${context}.model_id`),
        model_version: parseString(record.model_version, `${context}.model_version`),
        assumptions_digest: parseDigest(record.assumptions_digest, `${context}.assumptions_digest`),
        calculation_version: parseString(record.calculation_version, `${context}.calculation_version`),
    };
};

const parseArtifactHashes = (
    value: unknown,
    context: string
): FundamentalArtifactHashes => {
    const record = parseRecord(value, context);
    const dataReleaseDigest = record.data_release_manifest_digest;
    return {
        input_digest: parseDigest(record.input_digest, `${context}.input_digest`),
        result_hash: parseDigest(record.result_hash, `${context}.result_hash`),
        snapshot_manifest_digest: parseDigest(record.snapshot_manifest_digest, `${context}.snapshot_manifest_digest`),
        ...(dataReleaseDigest === undefined || dataReleaseDigest === null
            ? {}
            : { data_release_manifest_digest: parseDigest(dataReleaseDigest, `${context}.data_release_manifest_digest`) }),
        source_content_hashes: parseRequiredDigestArray(record.source_content_hashes, `${context}.source_content_hashes`),
    };
};

const parseOptionalArtifactNumber = (value: unknown, context: string): number | undefined => {
    if (value === undefined || value === null) return undefined;
    if (typeof value === 'string') {
        const numeric = Number(value);
        if (value.trim().length === 0 || !Number.isFinite(numeric)) {
            throw new TypeError(`${context} must be a finite number.`);
        }
        return numeric;
    }
    return parseOptionalNumber(value, context);
};

const parseFactsOnlyArtifact = (
    record: Record<string, unknown>,
    context: string
): FundamentalServiceFactsOnlyArtifact => {
    const valuationFields = [
        'valuation_trace',
        'valuation_input',
        'input_digest',
        'result_hash',
        'intrinsic_value',
        'per_share_value',
        'calculation_version',
        'calculation_status',
        'evaluated_at',
    ];
    if (valuationFields.some((field) => record[field] !== undefined && record[field] !== null)) {
        throw new TypeError(`${context} facts-only projection cannot include valuation data.`);
    }
    if (record.contract_version !== 'fundamental.v1') {
        throw new TypeError(`${context}.contract_version must be fundamental.v1.`);
    }
    if (record.valuation_status !== 'not_requested') {
        throw new TypeError(`${context}.valuation_status must be not_requested.`);
    }
    const facts = parseFundamentalFacts(record.facts, `${context}.facts`);
    const snapshotId = parseString(record.snapshot_id, `${context}.snapshot_id`);
    const snapshotManifestDigest = parseDigest(
        record.snapshot_manifest_digest,
        `${context}.snapshot_manifest_digest`
    );
    const factIds = parseStringArray(record.fact_ids, `${context}.fact_ids`);
    if (snapshotId !== facts.snapshot_id) {
        throw new TypeError(`${context}.snapshot_id is not bound to facts.`);
    }
    if (snapshotManifestDigest !== facts.snapshot_manifest_digest) {
        throw new TypeError(`${context}.snapshot_manifest_digest is not bound to facts.`);
    }
    const expectedFactIds = facts.facts.map((fact) => fact.fact_id).sort();
    if ([...factIds].sort().join('\u0000') !== expectedFactIds.join('\u0000')) {
        throw new TypeError(`${context}.fact_ids are not bound to facts.`);
    }
    const provenance = parseProvenanceMetadata(record.provenance, `${context}.provenance`);
    if (provenance.snapshot_id !== undefined && provenance.snapshot_id !== snapshotId) {
        throw new TypeError(`${context}.provenance.snapshot_id does not match snapshot_id.`);
    }
    if (
        provenance.fact_ids !== undefined &&
        [...provenance.fact_ids].sort().join('\u0000') !== expectedFactIds.join('\u0000')
    ) {
        throw new TypeError(`${context}.provenance.fact_ids do not match facts.`);
    }
    const qualityRecord = parseRecord(record.quality, `${context}.quality`);
    const factsStatus = parseQuality(
        qualityRecord.facts_status,
        `${context}.quality.facts_status`
    );
    if (factsStatus !== facts.quality_status) {
        throw new TypeError(`${context}.quality.facts_status does not match facts.`);
    }
    const qualityIssueCodes = parseStringArray(
        qualityRecord.issue_codes,
        `${context}.quality.issue_codes`
    );
    const issueCodes = parseStringArray(record.issue_codes, `${context}.issue_codes`);
    if (qualityIssueCodes.join('\u0000') !== issueCodes.join('\u0000')) {
        throw new TypeError(`${context}.quality.issue_codes do not match issue_codes.`);
    }
    const hashesRecord = parseRecord(record.hashes, `${context}.hashes`);
    const hashSnapshotDigest = parseDigest(
        hashesRecord.snapshot_manifest_digest,
        `${context}.hashes.snapshot_manifest_digest`
    );
    if (hashSnapshotDigest !== snapshotManifestDigest) {
        throw new TypeError(`${context}.hashes.snapshot_manifest_digest does not match snapshot_manifest_digest.`);
    }
    const releaseDigestValue = parseOptionalString(
        hashesRecord.data_release_manifest_digest,
        `${context}.hashes.data_release_manifest_digest`
    );
    const releaseDigest = releaseDigestValue === undefined
        ? undefined
        : parseDigest(releaseDigestValue, `${context}.hashes.data_release_manifest_digest`);
    if (releaseDigest !== facts.data_release_manifest_digest) {
        throw new TypeError(`${context}.hashes.data_release_manifest_digest does not match facts.`);
    }
    const sourceContentHashes = parseRequiredDigestArray(
        hashesRecord.source_content_hashes,
        `${context}.hashes.source_content_hashes`
    );
    const expectedSourceHashes = [
        ...new Set(facts.facts.map((fact) => fact.source.source_hash)),
    ].sort();
    if ([...sourceContentHashes].sort().join('\u0000') !== expectedSourceHashes.join('\u0000')) {
        throw new TypeError(`${context}.hashes.source_content_hashes do not match facts.`);
    }
    return {
        projection_type: 'facts_only',
        valuation_status: 'not_requested',
        contract_version: 'fundamental.v1',
        snapshot_id: snapshotId,
        snapshot_manifest_digest: snapshotManifestDigest,
        fact_ids: factIds,
        facts,
        provenance,
        quality: { facts_status: factsStatus, issue_codes: qualityIssueCodes },
        hashes: {
            snapshot_manifest_digest: hashSnapshotDigest,
            ...(releaseDigest === undefined
                ? {}
                : { data_release_manifest_digest: releaseDigest }),
            source_content_hashes: sourceContentHashes,
        },
        issue_codes: issueCodes,
    };
};

const parseDegradedArtifact = (
    record: Record<string, unknown>,
    context: string
): FundamentalServiceDegradedArtifact => {
    if (record.contract_version !== 'fundamental.v1') {
        throw new TypeError(`${context}.contract_version must be fundamental.v1.`);
    }
    if (record.projection_type !== 'degraded') {
        throw new TypeError(`${context}.projection_type must be degraded.`);
    }
    if (record.valuation_status !== 'service_unavailable') {
        throw new TypeError(`${context}.valuation_status must be service_unavailable.`);
    }
    if (record.quality_status !== 'degraded') {
        throw new TypeError(`${context}.quality_status must be degraded.`);
    }
    const failure = parseRecord(record.service_failure, `${context}.service_failure`);
    return {
        projection_type: 'degraded',
        contract_version: 'fundamental.v1',
        valuation_status: 'service_unavailable',
        quality_status: 'degraded',
        issue_codes: parseStringArray(record.issue_codes, `${context}.issue_codes`),
        service_failure: {
            code: parseString(failure.code, `${context}.service_failure.code`),
            message: parseString(failure.message, `${context}.service_failure.message`),
            retryable: parseBoolean(failure.retryable, `${context}.service_failure.retryable`),
        },
    };
};

const parseValuationArtifact = (
    record: Record<string, unknown>,
    context: string
): FundamentalServiceValuationArtifact => {
    if (record.contract_version !== 'fundamental.v1') {
        throw new TypeError(`${context}.contract_version must be fundamental.v1.`);
    }
    if (record.projection_type !== undefined && record.projection_type !== 'valuation') {
        throw new TypeError(`${context}.projection_type must be valuation.`);
    }
    const facts = parseFundamentalFacts(record.facts, `${context}.facts`);
    const snapshotId = parseString(record.snapshot_id, `${context}.snapshot_id`);
    const snapshotManifestDigest = parseDigest(
        record.snapshot_manifest_digest,
        `${context}.snapshot_manifest_digest`
    );
    const factIds = parseStringArray(record.fact_ids, `${context}.fact_ids`);
    const valuationTrace = parseValuationTrace(record.valuation_trace, `${context}.valuation_trace`);
    if (snapshotId !== facts.snapshot_id || snapshotId !== valuationTrace.snapshot_id) {
        throw new TypeError(`${context} snapshot_id is not bound to facts and valuation_trace.`);
    }
    if (
        snapshotManifestDigest !== facts.snapshot_manifest_digest ||
        snapshotManifestDigest !== valuationTrace.snapshot_manifest_digest
    ) {
        throw new TypeError(`${context} snapshot_manifest_digest is not bound to facts and valuation_trace.`);
    }
    const expectedFactIds = [...facts.facts].map((fact) => fact.fact_id).sort();
    const actualFactIds = [...factIds].sort();
    const traceFactIds = [...valuationTrace.fact_ids].sort();
    if (
        actualFactIds.length === 0 ||
        actualFactIds.join('\u0000') !== expectedFactIds.join('\u0000') ||
        traceFactIds.join('\u0000') !== expectedFactIds.join('\u0000')
    ) {
        throw new TypeError(`${context}.fact_ids are not bound to facts and valuation_trace.`);
    }
    const provenance = parseProvenanceMetadata(record.provenance, `${context}.provenance`);
    if (provenance.snapshot_id !== undefined && provenance.snapshot_id !== snapshotId) {
        throw new TypeError(`${context}.provenance.snapshot_id does not match snapshot_id.`);
    }
    if (provenance.fact_ids !== undefined && [...provenance.fact_ids].sort().join('\u0000') !== expectedFactIds.join('\u0000')) {
        throw new TypeError(`${context}.provenance.fact_ids do not match facts.`);
    }
    const quality = parseQualityMetadata(record.quality, `${context}.quality`);
    const hashes = parseArtifactHashes(record.hashes, `${context}.hashes`);
    if (hashes.snapshot_manifest_digest !== snapshotManifestDigest) {
        throw new TypeError(`${context}.hashes.snapshot_manifest_digest does not match snapshot_manifest_digest.`);
    }
    const parseOptionalProjectionString = (field: keyof FundamentalServiceValuationArtifact): string | undefined =>
        parseOptionalString(record[field], `${context}.${field}`);
    const qualityStatus = parseOptionalProjectionString('quality_status');
    const parsed: FundamentalServiceValuationArtifact = {
        projection_type: 'valuation',
        contract_version: 'fundamental.v1',
        snapshot_id: snapshotId,
        snapshot_manifest_digest: snapshotManifestDigest,
        fact_ids: factIds,
        facts,
        valuation_trace: valuationTrace,
        provenance,
        quality,
        hashes,
        issue_codes: parseStringArray(record.issue_codes, `${context}.issue_codes`),
        missing_evidence: parseStringArray(record.missing_evidence, `${context}.missing_evidence`),
    };
    const automaticPreparation =
        record.automatic_preparation === undefined || record.automatic_preparation === null
            ? undefined
            : parseAutomaticPreparation(record.automatic_preparation, `${context}.automatic_preparation`);
    if (automaticPreparation !== undefined) parsed.automatic_preparation = automaticPreparation;
    if (record.valuation_input !== undefined && record.valuation_input !== null) {
        parsed.valuation_input = parseRecord(record.valuation_input, `${context}.valuation_input`);
    }
    const modelId = parseOptionalProjectionString('model_id');
    if (modelId !== undefined) parsed.model_id = modelId;
    const modelVersion = parseOptionalProjectionString('model_version');
    if (modelVersion !== undefined) parsed.model_version = modelVersion;
    const calculationVersion = parseOptionalProjectionString('calculation_version');
    if (calculationVersion !== undefined) parsed.calculation_version = calculationVersion;
    const calculationStatus = parseOptionalProjectionString('calculation_status');
    if (calculationStatus !== undefined) parsed.calculation_status = calculationStatus;
    const inputDigest = parseOptionalProjectionString('input_digest');
    if (inputDigest !== undefined) parsed.input_digest = parseDigest(inputDigest, `${context}.input_digest`);
    const resultHash = parseOptionalProjectionString('result_hash');
    if (resultHash !== undefined) parsed.result_hash = parseDigest(resultHash, `${context}.result_hash`);
    const evaluatedAt = parseOptionalProjectionString('evaluated_at');
    if (evaluatedAt !== undefined) parsed.evaluated_at = parseTimestamp(evaluatedAt, `${context}.evaluated_at`);
    if (qualityStatus !== undefined) parsed.quality_status = parseQuality(qualityStatus, `${context}.quality_status`);
    const serviceResult = record.service_result === undefined || record.service_result === null
        ? undefined
        : parseRecord(record.service_result, `${context}.service_result`);
    const intrinsicValue = parseOptionalArtifactNumber(
        record.intrinsic_value ?? serviceResult?.intrinsic_value,
        `${context}.intrinsic_value`
    );
    if (intrinsicValue !== undefined) parsed.intrinsic_value = intrinsicValue;
    const perShareValue = parseOptionalArtifactNumber(
        record.per_share_value ?? serviceResult?.per_share_value,
        `${context}.per_share_value`
    );
    if (perShareValue !== undefined) parsed.per_share_value = perShareValue;
    return parsed;
};

export const parseFundamentalServiceArtifact = (
    value: unknown,
    context = 'fundamental_service'
): FundamentalServiceArtifact => {
    const record = parseRecord(value, context);
    if (record.projection_type === 'facts_only') {
        return parseFactsOnlyArtifact(record, context);
    }
    if (record.projection_type === 'degraded') {
        return parseDegradedArtifact(record, context);
    }
    if (record.projection_type !== undefined && record.projection_type !== 'valuation') {
        throw new TypeError(`${context}.projection_type must be valuation | facts_only | degraded.`);
    }
    return parseValuationArtifact(record, context);
};
