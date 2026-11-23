import type { components } from '@/types/generated/api-contract';
import { isRecord } from '../preview';

type Contracts = components['schemas'];
type Parser<T> = (value: unknown, context: string) => T;
type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export type FundamentalAutomaticPreparation = Contracts['FundamentalValuationPreparationResultV1'];
export type FundamentalAssumptionEvidence = Contracts['FundamentalAssumptionEvidenceV1'];
export type FundamentalServiceArtifact =
    | Contracts['FundamentalValuationReportV1']
    | Contracts['FundamentalFactsOnlyReportV1']
    | Contracts['FundamentalPreparationOutcomeV1']
    | Contracts['FundamentalDegradedReportV1'];

function record(value: unknown, context: string): Record<string, unknown> {
    if (!isRecord(value) || Array.isArray(value)) {
        throw new TypeError(`${context} must be an object.`);
    }
    return value;
}

function isContractObject<T extends object>(value: unknown, fields: { [K in keyof T]-?: Parser<T[K]> }, context: string): value is T {
    const input = record(value, context);
    for (const key of Object.keys(input)) {
        if (!Object.hasOwn(fields, key)) throw new TypeError(`${context}.${key} is unsupported.`);
    }
    for (const key in fields) fields[key](input[key], `${context}.${key}`);
    return true;
}

function object<T extends object>(fields: { [K in keyof T]-?: Parser<T[K]> }): Parser<T> {
    return (value, context) => {
        if (isContractObject(value, fields, context)) return value;
        throw new TypeError(`${context} does not match the contract.`);
    };
}

const text: Parser<string> = (value, context) => {
    if (typeof value !== 'string') throw new TypeError(`${context} must be a string.`);
    return value;
};
const nonEmpty: Parser<string> = (value, context) => {
    const parsed = text(value, context);
    if (!parsed.length) throw new TypeError(`${context} must be non-empty.`);
    return parsed;
};
const boolean: Parser<boolean> = (value, context) => {
    if (typeof value !== 'boolean') throw new TypeError(`${context} must be a boolean.`);
    return value;
};
const integer: Parser<number> = (value, context) => {
    if (typeof value !== 'number' || !Number.isSafeInteger(value)) throw new TypeError(`${context} must be a safe integer.`);
    return value;
};
const nullValue: Parser<null> = (value, context) => {
    if (value !== null) throw new TypeError(`${context} must be null.`);
    return value;
};
function optional<T>(parse: Parser<T>): Parser<T | undefined> {
    return (value, context) => value === undefined ? undefined : parse(value, context);
}
function literal<const T extends string>(...choices: T[]): Parser<T> {
    return (value, context) => {
        const parsed = choices.find((choice) => choice === value);
        if (parsed === undefined) throw new TypeError(`${context} must be ${choices.join(' | ')}.`);
        return parsed;
    };
}
function union<A, B>(first: Parser<A>, second: Parser<B>): Parser<A | B> {
    return (value, context) => {
        try { return first(value, context); } catch (error) {
            if (!(error instanceof TypeError)) throw error;
        }
        return second(value, context);
    };
}
function array<T>(parse: Parser<T>): Parser<T[]> {
    return (value, context) => {
        if (!Array.isArray(value)) throw new TypeError(`${context} must be an array.`);
        return value.map((item, index) => parse(item, `${context}[${index}]`));
    };
}
function dictionary<T>(parse: Parser<T>): Parser<Record<string, T>> {
    return (value, context) => Object.fromEntries(Object.entries(record(value, context)).map(
        ([key, item]) => [key, parse(item, `${context}.${key}`)],
    ));
}
const json: Parser<JsonValue> = (value, context) => {
    if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (Array.isArray(value)) return array(json)(value, context);
    return dictionary(json)(value, context);
};
function matching(pattern: RegExp, description: string): Parser<string> {
    return (value, context) => {
        const parsed = text(value, context);
        if (!pattern.test(parsed)) throw new TypeError(`${context} must be ${description}.`);
        return parsed;
    };
}
const decimal = matching(/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/, 'canonical Decimal text');
const integerText = matching(/^(?:0|-?[1-9][0-9]*)$/, 'canonical integer text');
const digest = matching(/^[0-9a-f]{64}$/, 'a lowercase SHA-256 digest');
const date = matching(/^\d{4}-\d{2}-\d{2}$/, 'an ISO date');
const timestamp: Parser<string> = (value, context) => {
    const parsed = text(value, context);
    if (!/^\d{4}-\d{2}-\d{2}T/.test(parsed) || !Number.isFinite(Date.parse(parsed))) {
        throw new TypeError(`${context} must be an ISO timestamp.`);
    }
    return parsed;
};

const parseFundamentalForwardReferenceProvenance = object<Contracts['FundamentalForwardReferenceProvenanceV1']>({
    citation: text,
    claim_id: text,
    license_reference: text,
    source_content_hash: digest,
    source_url: text,
});

const parseFundamentalManualProvenance = object<Contracts['FundamentalManualProvenanceV1']>({
    author: text,
    automatic_preparation_digest: digest,
    forward_reference: optional(union(parseFundamentalForwardReferenceProvenance, nullValue)),
    modified_at: timestamp,
    reason: text,
});

const parseFundamentalAssumptionEvidence = object<Contracts['FundamentalAssumptionEvidenceV1']>({
    as_of: timestamp,
    editable: boolean,
    fact_ids: array(text),
    formula: text,
    manual_provenance: optional(union(parseFundamentalManualProvenance, nullValue)),
    method: literal("derived", "approved_source", "approved_policy", "manual"),
    path: text,
    policy_version: text,
    source_refs: array(text),
    value: decimal,
});

const parseFundamentalHistoricalMetric = object<Contracts['FundamentalHistoricalMetricV1']>({
    fact_ids: array(text),
    fiscal_year: integer,
    formula: text,
    metric_id: text,
    period_end: text,
    source_refs: array(text),
    unit: text,
    value: decimal,
});

const parseFundamentalHistoricalMetrics = object<Contracts['FundamentalHistoricalMetricsV1']>({
    issue_codes: array(text),
    metrics: array(parseFundamentalHistoricalMetric),
    missing_evidence: array(text),
    profile_digest: digest,
    profile_id: text,
    quality_status: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
    working_capital_assessments: optional(array(dictionary(json))),
    working_capital_inputs: optional(array(dictionary(json))),
});

const parseFundamentalValuationPreparationResult = object<Contracts['FundamentalValuationPreparationResultV1']>({
    assumptions_evidence: array(parseFundamentalAssumptionEvidence),
    conditional_capital: optional(union(dictionary(json), nullValue)),
    conditional_operating: optional(union(dictionary(json), nullValue)),
    conditional_quote: optional(union(dictionary(json), nullValue)),
    contract_version: literal("fundamental.v1"),
    equity_dilution: optional(union(dictionary(json), nullValue)),
    historical_metrics: parseFundamentalHistoricalMetrics,
    input: optional(union(dictionary(json), nullValue)),
    issue_codes: array(text),
    missing_evidence: array(text),
    model_id: literal("fcff_dcf", "transition_fcff_dcf"),
    model_version: nonEmpty,
    policy_id: nonEmpty,
    policy_version: nonEmpty,
    preparation_digest: digest,
    profile_digest: digest,
    profile_id: nonEmpty,
    quality_status: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
    status: literal("prepared", "requires_input", "abstained", "unsupported"),
});

const parseFundamentalDimension = object<Contracts['FundamentalDimensionV1']>({
    member: nonEmpty,
    name: nonEmpty,
});

const parseFundamentalXbrlContext = object<Contracts['FundamentalXbrlContextV1']>({
    concept_qname: nonEmpty,
    consolidation_scope: nonEmpty,
    context_id: nonEmpty,
    dimensions: array(parseFundamentalDimension),
    end_date: optional(union(date, nullValue)),
    entity_scope: nonEmpty,
    instant: optional(union(date, nullValue)),
    measure: nonEmpty,
    period_type: literal("instant", "duration"),
    start_date: optional(union(date, nullValue)),
    unit_qname: nonEmpty,
});

const parseFundamentalCandidateRejection = object<Contracts['FundamentalCandidateRejectionV1']>({
    candidate_id: nonEmpty,
    reason: nonEmpty,
});

const parseFundamentalSourceProvenance = object<Contracts['FundamentalSourceProvenanceV1']>({
    accession_number: optional(union(text, nullValue)),
    available_at: timestamp,
    captured_at: timestamp,
    content_hash: digest,
    filed_at: optional(union(timestamp, nullValue)),
    parser_version: nonEmpty,
    source_role: literal("filing", "company_facts", "taxonomy", "acquisition", "macro", "market", "reference"),
    source_url: nonEmpty,
    taxonomy_version: optional(union(text, nullValue)),
    terms_reference: optional(union(text, nullValue)),
});

const parseFundamentalMissingValue = object<Contracts['FundamentalMissingValueV1']>({
    reason: nonEmpty,
    status: literal("missing", "not_applicable", "unsupported", "unresolved"),
});

const parseFundamentalCanonicalFact = object<Contracts['FundamentalCanonicalFactV1']>({
    accession_number: optional(union(text, nullValue)),
    accounting_evidence: optional(union(dictionary(json), nullValue)),
    amendment_scope: optional(union(literal("valuation_relevant", "unrelated", "unknown"), nullValue)),
    amends_accession: optional(union(text, nullValue)),
    as_of: timestamp,
    available_at: timestamp,
    captured_at: timestamp,
    concept: nonEmpty,
    context: parseFundamentalXbrlContext,
    contract_version: literal("fundamental.v1"),
    currency: optional(union(text, nullValue)),
    decimals: optional(union(integer, nullValue)),
    fact_id: nonEmpty,
    filed_at: optional(union(timestamp, nullValue)),
    filing_version: optional(union(text, nullValue)),
    instant: optional(union(date, nullValue)),
    is_amendment: boolean,
    issue_codes: array(text),
    issuer_id: nonEmpty,
    mapping_confidence: optional(union(literal("high", "medium", "low", "unresolved"), nullValue)),
    mapping_decision_id: optional(union(text, nullValue)),
    normalized_field: nonEmpty,
    period_end: date,
    period_start: optional(union(date, nullValue)),
    point_in_time_policy: optional(union(text, nullValue)),
    quality: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
    rejected_candidate_reasons: array(parseFundamentalCandidateRejection),
    rejected_candidates: array(text),
    scale: integer,
    security_id: optional(union(text, nullValue)),
    security_scope: optional(union(text, nullValue)),
    selection_reason: optional(union(text, nullValue)),
    source: parseFundamentalSourceProvenance,
    supersedes_accession: optional(union(text, nullValue)),
    taxonomy_version: nonEmpty,
    unit: nonEmpty,
    value: union(text, union(boolean, parseFundamentalMissingValue)),
});

const parseFundamentalIdentity = object<Contracts['FundamentalIdentityV1']>({
    currency: nonEmpty,
    domicile: nonEmpty,
    issuer_id: nonEmpty,
    issuer_name: nonEmpty,
    reporting_basis: literal("us-gaap", "ifrs"),
    security_id: nonEmpty,
    share_class: nonEmpty,
});

const parseFundamentalBoundFacts = object<Contracts['FundamentalBoundFactsV1']>({
    contract_version: literal("fundamental.v1"),
    data_release_manifest_digest: optional(union(digest, nullValue)),
    fact_ids: array(text),
    facts: array(parseFundamentalCanonicalFact),
    identity: parseFundamentalIdentity,
    issue_codes: array(text),
    quality_status: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
    snapshot_id: nonEmpty,
    snapshot_manifest_digest: digest,
    valuation_timestamp: timestamp,
});

const parseFundamentalReportHashes = object<Contracts['FundamentalReportHashesV1']>({
    data_release_manifest_digest: optional(union(digest, nullValue)),
    input_digest: optional(union(digest, nullValue)),
    result_hash: optional(union(digest, nullValue)),
    snapshot_manifest_digest: digest,
    source_content_hashes: array(digest),
});

const parseFundamentalFactsQuality = object<Contracts['FundamentalFactsQualityV1']>({
    facts_status: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
    issue_codes: array(text),
    missing_fields: array(text),
    rejected_fact_ids: array(text),
});

const parseFundamentalValuationEvidence = object<Contracts['FundamentalValuationEvidenceV1']>({
    contract_version: literal("fundamental.v1"),
    data_release_manifest_digest: digest,
    fact_ids: array(text),
    facts: array(parseFundamentalCanonicalFact),
    hashes: parseFundamentalReportHashes,
    identity: parseFundamentalIdentity,
    issue_codes: array(text),
    missing_fields: array(text),
    model_id: literal("fcff_dcf", "transition_fcff_dcf"),
    profile_digest: digest,
    profile_id: nonEmpty,
    projection_type: literal("valuation_evidence"),
    provenance: dictionary(json),
    quality: parseFundamentalFactsQuality,
    quality_status: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
    rejected_fact_ids: array(text),
    snapshot_id: nonEmpty,
    snapshot_manifest_digest: digest,
    snapshot_timestamp: timestamp,
    valuation_timestamp: timestamp,
});

const parseFundamentalValuationQuality = object<Contracts['FundamentalValuationQualityV1']>({
    calculation_status: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
    facts_status: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
    input: dictionary(json),
    issue_codes: array(text),
    validation_status: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
});

const parseFundamentalServiceEvidenceReference = object<Contracts['FundamentalServiceEvidenceReferenceV1']>({
    artifact_id: text,
    artifact_type: literal("calculation_evidence", "uncertainty_evidence"),
    content_hash: digest,
    media_type: literal("application/json"),
});

const parseFundamentalTrace = object<Contracts['FundamentalTraceV1']>({
    as_of: optional(union(timestamp, nullValue)),
    available_at: optional(union(timestamp, nullValue)),
    captured_at: optional(union(timestamp, nullValue)),
    description: optional(union(text, nullValue)),
    expression: optional(union(text, nullValue)),
    inputs: array(text),
    source_ids: array(text),
    source_refs: array(text),
    source_uris: array(text),
    source_versions: array(text),
    terms_references: array(text),
});

const parseFundamentalCalculationNode = object<Contracts['FundamentalCalculationNodeV1']>({
    formula: text,
    inputs: array(text),
    node_id: text,
    trace: parseFundamentalTrace,
    unit: text,
    value: optional(union(decimal, nullValue)),
});

const parseFundamentalPolicyResolution = object<Contracts['FundamentalPolicyResolutionV1']>({
    contract_version: literal("fundamental.v1"),
    input_digest: digest,
    policy_digest: digest,
    policy_id: text,
    policy_version: text,
    precedence: dictionary(literal("caller", "policy")),
    resolved_fields: dictionary(json),
    selection_mode: literal("pinned", "exploratory_active"),
});

const parseFundamentalFiscalPeriod = object<Contracts['FundamentalFiscalPeriodV1']>({
    fiscal_year: integer,
});

const parseFundamentalFiscalPeriodSelector = object<Contracts['FundamentalFiscalPeriodSelectorV1']>({
    count: optional(union(integer, nullValue)),
    mode: literal("latest_complete", "explicit_periods"),
    periods: array(parseFundamentalFiscalPeriod),
    version: literal("fundamental.fiscal-period-selector.v1"),
});

const parseFundamentalResolvedFiscalPeriod = object<Contracts['FundamentalResolvedFiscalPeriodV1']>({
    available_at: timestamp,
    fiscal_year: integer,
    period_end: date,
    period_start: date,
});

const parseFundamentalCalculationTrace = object<Contracts['FundamentalCalculationTraceV1']>({
    assumptions_digest: digest,
    calculation_version: text,
    data_release_manifest_digest: optional(union(digest, nullValue)),
    fact_ids: array(text),
    fiscal_period_selector: parseFundamentalFiscalPeriodSelector,
    model_id: text,
    model_version: text,
    policy_digest: digest,
    policy_id: text,
    policy_version: text,
    resolved_fiscal_periods: array(parseFundamentalResolvedFiscalPeriod),
    snapshot_id: text,
    snapshot_manifest_digest: digest,
    source_content_hashes: array(digest),
    source_selection_policy: text,
    source_selection_policy_version: text,
    valuation_timestamp: timestamp,
});

const parseFundamentalCalculationResult = object<Contracts['FundamentalCalculationResultV1']>({
    artifact_references: array(parseFundamentalServiceEvidenceReference),
    assumptions: dictionary(json),
    calculation_status: literal("completed", "abstained", "rejected", "unavailable", "error"),
    calculation_version: text,
    contract_version: literal("fundamental.v1"),
    correlation_id: text,
    evaluated_at: timestamp,
    input_digest: digest,
    intrinsic_value: optional(union(decimal, nullValue)),
    issue_codes: array(text),
    missing_evidence: array(text),
    model_version: text,
    nodes: array(parseFundamentalCalculationNode),
    per_share_value: optional(union(decimal, nullValue)),
    policy_id: optional(union(text, nullValue)),
    policy_resolution: optional(union(parseFundamentalPolicyResolution, nullValue)),
    policy_version: optional(union(text, nullValue)),
    quality_status: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
    result_hash: digest,
    snapshot_id: text,
    trace: optional(union(parseFundamentalCalculationTrace, nullValue)),
    valuation_timestamp: timestamp,
});

const parseFundamentalConvergenceDiagnostics = object<Contracts['FundamentalConvergenceDiagnosticsV1']>({
    converged: optional(union(boolean, nullValue)),
    invalid_ratio: optional(union(decimal, nullValue)),
    minimum_valid_samples: optional(union(integer, nullValue)),
});

const sampledPaths: Parser<Contracts['FundamentalConditionalQuantileBasisV1']['sampled_paths']> = (value, context) => {
    if (!Array.isArray(value) || value.length !== 3) throw new TypeError(`${context} must contain the three ordered sampled paths.`);
    return [
        literal('assumptions.forecast.revenue_growth[0]')(value[0], `${context}[0]`),
        literal('assumptions.forecast.operating_margin[0]')(value[1], `${context}[1]`),
        literal('assumptions.terminal_growth')(value[2], `${context}[2]`),
    ];
};
const parseFundamentalConditionalQuantileBasis = object<Contracts['FundamentalConditionalQuantileBasisV1']>({
    conditioning: literal('retained_base_joint_hypotheses'),
    joint_scenarios_digest: digest,
    conditioning_assumptions_digest: digest,
    policy_version: literal('conditional-fcff-monte-carlo-policy-v1'),
    sampled_paths: sampledPaths,
    hypothesis_probabilities: literal('not_assigned'),
});

const parseFundamentalUncertaintyResult = object<Contracts['FundamentalUncertaintyResultV1']>({
    artifact_references: array(parseFundamentalServiceEvidenceReference),
    base: parseFundamentalCalculationResult,
    convergence_diagnostics: optional(parseFundamentalConvergenceDiagnostics),
    dominant_drivers: array(text),
    input_digest: digest,
    invalid_draw_policy: optional(union(text, nullValue)),
    invalid_reasons: optional(dictionary(integer)),
    invalid_samples: integer,
    quantile_contract: optional(dictionary(text)),
    quantiles: optional(dictionary(decimal)),
    quantile_basis: optional(union(parseFundamentalConditionalQuantileBasis, nullValue)),
    requested_samples: integer,
    result_hash: digest,
    sampler_version: optional(union(text, nullValue)),
    scenario_results: array(parseFundamentalCalculationResult),
    seed: optional(union(integerText, nullValue)),
    sensitivity: optional(dictionary(array(decimal))),
    status: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
    valid_samples: integer,
});

export function parseFundamentalServiceResult(value: unknown, context = 'fundamental.service_result'): Contracts['FundamentalCalculationResultV1'] | Contracts['FundamentalUncertaintyResultV1'] {
    return 'base' in record(value, context)
        ? parseFundamentalUncertaintyResult(value, context)
        : parseFundamentalCalculationResult(value, context);
}

const parseFundamentalValuationReport = object<Contracts['FundamentalValuationReportV1']>({
    automatic_preparation: optional(union(parseFundamentalValuationPreparationResult, nullValue)),
    calculation_status: literal("completed", "abstained", "rejected", "unavailable", "error"),
    calculation_version: text,
    contract_version: literal("fundamental.v1"),
    correlation_id: text,
    fact_ids: array(text),
    facts: union(parseFundamentalBoundFacts, parseFundamentalValuationEvidence),
    hashes: parseFundamentalReportHashes,
    input_digest: digest,
    projection_type: literal("valuation"),
    provenance: dictionary(json),
    quality: parseFundamentalValuationQuality,
    quality_status: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
    result_hash: digest,
    service_result: parseFundamentalServiceResult,
    snapshot_id: text,
    snapshot_manifest_digest: digest,
    valuation_input: dictionary(json),
    valuation_trace: parseFundamentalCalculationTrace,
});

const parseFundamentalFactsOnlyReport = object<Contracts['FundamentalFactsOnlyReportV1']>({
    contract_version: literal("fundamental.v1"),
    fact_ids: array(text),
    facts: parseFundamentalBoundFacts,
    hashes: parseFundamentalReportHashes,
    issue_codes: array(text),
    projection_type: literal("facts_only"),
    provenance: dictionary(json),
    quality: parseFundamentalFactsQuality,
    snapshot_id: text,
    snapshot_manifest_digest: digest,
    snapshot_selector: dictionary(json),
    snapshot_timestamp: timestamp,
    valuation_status: literal("not_requested"),
});

const parseFundamentalPreparationOutcome = object<Contracts['FundamentalPreparationOutcomeV1']>({
    automatic_preparation: parseFundamentalValuationPreparationResult,
    contract_version: literal("fundamental.v1"),
    identity: parseFundamentalIdentity,
    issue_codes: array(text),
    missing_evidence: array(text),
    projection_type: literal("preparation_outcome"),
    quality_status: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
    reason: optional(union(text, nullValue)),
    snapshot_selector: dictionary(json),
    valuation_status: literal("requires_input", "abstained", "unsupported"),
});

const parseFundamentalServiceFailure = object<Contracts['FundamentalServiceFailureV1']>({
    code: text,
    message: text,
    retryable: boolean,
});

const parseFundamentalDegradedReport = object<Contracts['FundamentalDegradedReportV1']>({
    contract_version: literal("fundamental.v1"),
    issue_codes: array(text),
    projection_type: literal("degraded"),
    quality_status: literal("degraded"),
    service_failure: parseFundamentalServiceFailure,
    valuation_status: literal("service_unavailable"),
});

function assertSame(label: string, actual: unknown, expected: unknown) {
    if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new TypeError(`${label} identity mismatch.`);
}
function assertFactBinding(artifact: Extract<FundamentalServiceArtifact, { projection_type: 'valuation' | 'facts_only' }>, context: string) {
    const facts = artifact.facts;
    assertSame(`${context}.snapshot_id`, artifact.snapshot_id, facts.snapshot_id);
    assertSame(`${context}.snapshot_manifest_digest`, artifact.snapshot_manifest_digest, facts.snapshot_manifest_digest);
    const factIds = facts.facts.map((fact) => fact.fact_id).sort();
    if (new Set(factIds).size !== factIds.length) throw new TypeError(`${context}.facts contains duplicate fact_id.`);
    assertSame(`${context}.fact_ids`, [...artifact.fact_ids].sort(), factIds);
    assertSame(`${context}.facts.fact_ids`, [...facts.fact_ids].sort(), factIds);
    assertSame(`${context}.hashes.snapshot_manifest_digest`, artifact.hashes.snapshot_manifest_digest, facts.snapshot_manifest_digest);
    assertSame(`${context}.hashes.data_release_manifest_digest`, artifact.hashes.data_release_manifest_digest ?? null, facts.data_release_manifest_digest ?? null);
    assertSame(`${context}.hashes.source_content_hashes`, [...artifact.hashes.source_content_hashes].sort(), [...new Set(facts.facts.map((fact) => fact.source.content_hash))].sort());
}

export function parseFundamentalAutomaticPreparation(value: unknown, context = 'fundamental.automatic_preparation'): FundamentalAutomaticPreparation {
    const preparation = parseFundamentalValuationPreparationResult(value, context);
    if ((preparation.status === 'prepared') !== (preparation.input != null)) throw new TypeError(`${context}.status must match input presence.`);
    for (const evidence of preparation.assumptions_evidence) {
        if ((evidence.method === 'manual') !== (evidence.manual_provenance != null)) throw new TypeError(`${context}.manual_provenance must match method.`);
    }
    return preparation;
}

export function parseFundamentalServiceArtifact(value: unknown, context = 'fundamental_service'): FundamentalServiceArtifact {
    const input = record(value, context);
    switch (input.projection_type) {
        case 'degraded': return parseFundamentalDegradedReport(value, context);
        case 'preparation_outcome': {
            const outcome = parseFundamentalPreparationOutcome(value, context);
            const preparation = parseFundamentalAutomaticPreparation(outcome.automatic_preparation, `${context}.automatic_preparation`);
            assertSame(`${context}.valuation_status`, outcome.valuation_status, preparation.status);
            return outcome;
        }
        case 'facts_only': {
            const factsOnly = parseFundamentalFactsOnlyReport(value, context);
            assertFactBinding(factsOnly, context);
            return factsOnly;
        }
        case 'valuation': {
            const valuation = parseFundamentalValuationReport(value, context);
            assertFactBinding(valuation, context);
            const result = valuation.service_result;
            const base = 'base' in result ? result.base : result;
            assertSame(`${context}.input_digest`, valuation.input_digest, result.input_digest);
            assertSame(`${context}.result_hash`, valuation.result_hash, result.result_hash);
            assertSame(`${context}.hashes.input_digest`, valuation.hashes.input_digest, result.input_digest);
            assertSame(`${context}.hashes.result_hash`, valuation.hashes.result_hash, result.result_hash);
            assertSame(`${context}.quality_status`, valuation.quality_status, 'base' in result ? result.status : result.quality_status);
            assertSame(`${context}.calculation_status`, valuation.calculation_status, base.calculation_status);
            assertSame(`${context}.valuation_trace.snapshot_id`, valuation.valuation_trace.snapshot_id, valuation.snapshot_id);
            assertSame(`${context}.valuation_trace.snapshot_manifest_digest`, valuation.valuation_trace.snapshot_manifest_digest, valuation.snapshot_manifest_digest);
            assertSame(`${context}.valuation_trace.fact_ids`, [...valuation.valuation_trace.fact_ids].sort(), [...valuation.fact_ids].sort());
            assertSame(`${context}.service_result.snapshot_id`, base.snapshot_id, valuation.snapshot_id);
            if (valuation.automatic_preparation != null) parseFundamentalAutomaticPreparation(valuation.automatic_preparation, `${context}.automatic_preparation`);
            return valuation;
        }
        default: throw new TypeError(`${context}.projection_type must be valuation | facts_only | preparation_outcome | degraded.`);
    }
}
