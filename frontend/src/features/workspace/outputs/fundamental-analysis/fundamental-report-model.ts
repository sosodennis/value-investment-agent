import type { components } from '@/types/generated/api-contract';
import type { ArtifactReference } from '@/types/agents';
import type { FundamentalServiceArtifact } from '@/types/agents/fundamental-service-facts';
import { getArtifactRunId } from '@/features/artifacts/api';
import type { EvidenceSelection } from '../../workspace-evidence-inspector';

type Contracts = components['schemas'];
type Calculation = Contracts['FundamentalCalculationResultV1'];
type Fact = Contracts['FundamentalCanonicalFactV1'];
type Quality = Calculation['quality_status'];
type Binding = { inputDigest: string; resultHash: string };

export type ExactNumber = { raw: string; coordinate: number | null };
export type ExactAmount = ExactNumber & { currency: string; basis: 'equity-total' | 'per-share' };
export type FundamentalReportIdentity = {
    threadId: string | null;
    runId: string | null;
    artifactId: string | null;
    artifactUrl: string | null;
    preparationDigest: string | null;
};
export type FundamentalFactModel = {
    id: string;
    label: string;
    value: string;
    period: string;
    unit: string;
    scale: number;
    currency: string | null;
    dimensions: { name: string; member: string }[];
    quality: Quality;
    issueCodes: string[];
    evidence: EvidenceSelection;
};
type CalculationModel = {
    binding: Binding;
    status: Calculation['calculation_status'];
    quality: Quality;
    equity: ExactAmount | null;
    perShare: ExactAmount | null;
    evaluatedAt: string;
    valuationDate: string;
    issueCodes: string[];
    missingEvidence: string[];
    nodes: { id: string; value: ExactNumber | null; unit: string; formula: string; inputs: string[]; evidence: EvidenceSelection }[];
    evidenceReferences: Contracts['FundamentalServiceEvidenceReferenceV1'][];
};
export type PreparationSummary = {
    digest: string;
    status: Contracts['FundamentalValuationPreparationResultV1']['status'];
    modelId: string;
    modelVersion: string;
    policyId: string;
    policyVersion: string;
    quality: Quality;
    issueCodes: string[];
    missingEvidence: string[];
    assumptions: { path: string; value: ExactNumber; method: string; editable: boolean; isManual: boolean; formula: string; evidence: EvidenceSelection }[];
    historicalMetrics: { id: string; year: number; value: ExactNumber; unit: string; periodEnd: string; formula: string; factIds: string[] }[];
};
type UncertaintyModel = {
    kind: 'provided';
    mode: 'sampled' | 'scenarios';
    binding: Binding;
    quality: Quality;
    quantiles: { label: string; value: ExactAmount; evidence: EvidenceSelection }[];
    quantileContract: { label: string; quantile: string }[];
    quantileBasis: Contracts['FundamentalConditionalQuantileBasisV1'] | null;
    requestedSamples: number;
    validSamples: number;
    invalidSamples: number;
    invalidReasons: { code: string; count: number }[];
    seed: string | null;
    samplerVersion: string | null;
    invalidDrawPolicy: string | null;
    convergence: { minimumValidSamples: number | null; invalidRatio: ExactNumber | null; converged: boolean | null };
    sensitivity: { path: string; values: ExactNumber[] }[];
    dominantDrivers: string[];
    scenarios: CalculationModel[];
    evidenceReferences: Contracts['FundamentalServiceEvidenceReferenceV1'][];
};
type ReportBase = {
    identity: FundamentalReportIdentity;
    company: string;
    shareClass: string | null;
    currency: string | null;
    quality: Quality;
    issueCodes: string[];
    facts: FundamentalFactModel[];
};
export type FundamentalReportModel =
    | (ReportBase & {
        kind: 'valuation';
        modelId: string;
        modelVersion: string;
        calculationVersion: string;
        snapshotId: string;
        snapshotDigest: string;
        releaseDigest: string | null;
        reportBinding: Binding;
        base: CalculationModel;
        uncertainty: UncertaintyModel | { kind: 'not-requested' };
        preparationSummary: PreparationSummary | null;
    })
    | (ReportBase & { kind: 'facts-only'; snapshotId: string; valuationDate: string })
    | (ReportBase & {
        kind: 'preparation-outcome';
        outcome: 'requires_input' | 'abstained' | 'unsupported';
        reason: string | null;
        missingEvidence: string[];
        preparationSummary: PreparationSummary;
    })
    | (ReportBase & { kind: 'service-error'; code: string; message: string; retryable: boolean });

export type FundamentalValuationModel = Extract<FundamentalReportModel, { kind: 'valuation' }>;
export type FundamentalEvidenceInventory = { sourceKey: string; items: EvidenceSelection[] };

export function fundamentalReportSourceKey({ threadId, reference }: { threadId?: string | null; reference: ArtifactReference | null }): string {
    return JSON.stringify([threadId ?? null, getArtifactRunId(reference), reference?.artifact_id ?? null, reference?.download_url ?? null]);
}

function evidenceKey(identity: FundamentalReportIdentity, kind: string, id: string): string {
    return JSON.stringify([identity.threadId, identity.runId, identity.artifactId, identity.preparationDigest, kind, id]);
}

export function buildFundamentalEvidenceInventory(report: FundamentalReportModel): FundamentalEvidenceInventory {
    const items = report.facts.map((fact) => fact.evidence);
    if (report.kind === 'valuation' || report.kind === 'preparation-outcome') {
        items.push(...(report.preparationSummary?.assumptions.map((item) => item.evidence) ?? []));
    }
    if (report.kind === 'valuation') {
        items.push(...report.base.nodes.map((node) => node.evidence));
        if (report.uncertainty.kind === 'provided') {
            items.push(...report.uncertainty.quantiles.map((quantile) => quantile.evidence));
            items.push(...report.uncertainty.scenarios.flatMap((scenario) => scenario.nodes.map((node) => node.evidence)));
        }
    }
    return {
        sourceKey: JSON.stringify([report.identity.threadId, report.identity.runId, report.identity.artifactId, report.identity.artifactUrl]),
        items,
    };
}

export function exactNumber(raw: string): ExactNumber {
    const coordinate = Number(raw);
    return { raw, coordinate: Number.isFinite(coordinate) ? coordinate : null };
}

function amount(raw: string | null | undefined, currency: string, basis: ExactAmount['basis']): ExactAmount | null {
    return raw == null ? null : { ...exactNumber(raw), currency, basis };
}

function binding(result: Pick<Calculation, 'input_digest' | 'result_hash'>): Binding {
    return { inputDigest: result.input_digest, resultHash: result.result_hash };
}

function evidenceIdentity(identity: FundamentalReportIdentity) {
    return {
        threadId: identity.threadId ?? undefined,
        runId: identity.runId ?? undefined,
        preparationDigest: identity.preparationDigest ?? undefined,
        artifactId: identity.artifactId ?? undefined,
        artifactUrl: identity.artifactUrl ?? undefined,
    };
}

function factModel(fact: Fact, snapshotId: string, snapshotDigest: string, identity: FundamentalReportIdentity): FundamentalFactModel {
    const label = fact.normalized_field.replaceAll('_', ' ');
    const value = typeof fact.value === 'string' ? fact.value
        : typeof fact.value === 'boolean' ? String(fact.value)
            : `Unavailable · ${fact.value.status}: ${fact.value.reason}`;
    const period = fact.context.period_type === 'instant'
        ? `Instant · ${fact.instant ?? fact.context.instant ?? fact.period_end}`
        : `${fact.period_start ?? fact.context.start_date ?? 'Start unavailable'} → ${fact.period_end}`;
    return {
        id: fact.fact_id, label, value, period,
        unit: fact.unit, scale: fact.scale, currency: fact.currency ?? null,
        dimensions: fact.context.dimensions, quality: fact.quality, issueCodes: fact.issue_codes,
        evidence: {
            id: evidenceKey(identity, 'fact', fact.fact_id), title: `Service fact · ${label}`,
            value, period, source: `${fact.source.source_role} · ${fact.source.source_url}`,
            confidence: fact.quality, ...evidenceIdentity(identity),
            factId: fact.fact_id, concept: fact.concept,
            accessionNumber: fact.accession_number ?? fact.source.accession_number ?? undefined,
            capturedAt: fact.captured_at, availableAt: fact.available_at,
            filedAt: fact.filed_at ?? fact.source.filed_at ?? undefined,
            parserVersion: fact.source.parser_version, taxonomyVersion: fact.taxonomy_version,
            sourceHash: fact.source.content_hash, snapshotId, snapshotManifestDigest: snapshotDigest,
            unit: fact.unit, scale: fact.scale, issueCodes: fact.issue_codes,
            dimensions: fact.context.dimensions.map((dimension) => `${dimension.name}: ${dimension.member}`),
        },
    };
}

function calculationModel(result: Calculation, currency: string, identity: FundamentalReportIdentity, scope: string): CalculationModel {
    return {
        binding: binding(result), status: result.calculation_status, quality: result.quality_status,
        equity: amount(result.intrinsic_value, currency, 'equity-total'),
        perShare: amount(result.per_share_value, currency, 'per-share'),
        evaluatedAt: result.evaluated_at, valuationDate: result.valuation_timestamp,
        issueCodes: result.issue_codes, missingEvidence: result.missing_evidence,
        nodes: result.nodes.map((node) => ({
            id: node.node_id, value: node.value == null ? null : exactNumber(node.value),
            unit: node.unit, formula: node.formula, inputs: node.inputs,
            evidence: {
                id: evidenceKey(identity, 'node', `${scope}:${result.result_hash}:${node.node_id}`), title: `Calculation · ${node.node_id}`,
                value: node.value ?? 'Unavailable', unit: node.unit,
                formula: node.formula, source: [...node.trace.source_refs, ...node.trace.source_uris].join(', '),
                ...evidenceIdentity(identity),
                capturedAt: node.trace.captured_at ?? undefined, availableAt: node.trace.available_at ?? undefined,
                snapshotId: result.snapshot_id, confidence: result.quality_status,
                inputDigest: result.input_digest, resultHash: result.result_hash, inputs: node.inputs,
            },
        })),
        evidenceReferences: result.artifact_references,
    };
}

function preparationSummary(preparation: Contracts['FundamentalValuationPreparationResultV1'], identity: FundamentalReportIdentity): PreparationSummary {
    return {
        digest: preparation.preparation_digest, status: preparation.status,
        modelId: preparation.model_id, modelVersion: preparation.model_version,
        policyId: preparation.policy_id, policyVersion: preparation.policy_version,
        quality: preparation.quality_status, issueCodes: preparation.issue_codes, missingEvidence: preparation.missing_evidence,
        assumptions: preparation.assumptions_evidence.map((item, index) => ({
            path: item.path, value: exactNumber(item.value), method: item.method, editable: item.editable,
            isManual: item.method === 'manual' || item.manual_provenance != null, formula: item.formula,
            evidence: {
                id: evidenceKey(identity, 'assumption', `${item.path}:${index}`), title: `Assumption · ${item.path}`,
                value: item.value, formula: item.formula, source: item.source_refs.join(', '),
                period: item.as_of, confidence: item.method, inputs: item.fact_ids, ...evidenceIdentity(identity),
            },
        })),
        historicalMetrics: preparation.historical_metrics.metrics.map((metric) => ({
            id: metric.metric_id, year: metric.fiscal_year, value: exactNumber(metric.value),
            unit: metric.unit, periodEnd: metric.period_end, formula: metric.formula, factIds: metric.fact_ids,
        })),
    };
}

export function projectFundamentalReport({ artifact, reference, threadId = null, ticker }: {
    artifact: FundamentalServiceArtifact;
    reference: Pick<ArtifactReference, 'artifact_id' | 'download_url'> | null;
    threadId?: string | null;
    ticker: string;
}): FundamentalReportModel {
    const preparation = 'automatic_preparation' in artifact ? artifact.automatic_preparation : null;
    const identity: FundamentalReportIdentity = {
        threadId, runId: getArtifactRunId(reference), artifactId: reference?.artifact_id ?? null,
        artifactUrl: reference?.download_url ?? null, preparationDigest: preparation?.preparation_digest ?? null,
    };
    const companyIdentity = 'facts' in artifact ? artifact.facts.identity : 'identity' in artifact ? artifact.identity : null;
    const facts = 'facts' in artifact ? [...artifact.facts.facts].sort((a, b) => b.period_end.localeCompare(a.period_end) || a.fact_id.localeCompare(b.fact_id)).map(
        (fact) => factModel(fact, artifact.snapshot_id, artifact.snapshot_manifest_digest, identity),
    ) : [];
    const common = {
        identity, company: companyIdentity?.issuer_name ?? ticker, shareClass: companyIdentity?.share_class ?? null,
        currency: companyIdentity?.currency ?? null, quality: artifact.projection_type === 'facts_only' ? artifact.quality.facts_status : artifact.quality_status,
        issueCodes: artifact.projection_type === 'valuation' ? artifact.quality.issue_codes : artifact.issue_codes, facts,
    };
    switch (artifact.projection_type) {
        case 'degraded': return { ...common, kind: 'service-error', ...artifact.service_failure };
        case 'facts_only': return { ...common, kind: 'facts-only', snapshotId: artifact.snapshot_id, valuationDate: artifact.facts.valuation_timestamp };
        case 'preparation_outcome': return {
            ...common, kind: 'preparation-outcome', outcome: artifact.valuation_status,
            reason: artifact.reason ?? null, missingEvidence: artifact.missing_evidence,
            preparationSummary: preparationSummary(artifact.automatic_preparation, identity),
        };
        case 'valuation': {
            const result = artifact.service_result;
            const currency = artifact.facts.identity.currency;
            return {
                ...common, kind: 'valuation', modelId: artifact.valuation_trace.model_id,
                modelVersion: artifact.valuation_trace.model_version, calculationVersion: artifact.calculation_version,
                snapshotId: artifact.snapshot_id, snapshotDigest: artifact.snapshot_manifest_digest,
                releaseDigest: artifact.facts.data_release_manifest_digest ?? null,
                reportBinding: binding(result), base: calculationModel('base' in result ? result.base : result, currency, identity, 'base'),
                preparationSummary: artifact.automatic_preparation == null ? null : preparationSummary(artifact.automatic_preparation, identity),
                uncertainty: 'base' in result ? {
                    kind: 'provided', mode: result.requested_samples > 0 ? 'sampled' : 'scenarios', binding: binding(result), quality: result.status,
                    quantiles: Object.entries(result.quantiles ?? {}).map(([label, raw]) => ({
                        label, value: { ...exactNumber(raw), currency, basis: 'per-share' },
                        evidence: {
                            id: evidenceKey(identity, 'quantile', label), title: `Model quantile · ${label}`,
                            value: raw, unit: `${currency} / share`, confidence: result.status,
                            source: result.artifact_references.map((item) => `${item.artifact_type} · ${item.artifact_id}`).join(', '),
                            inputDigest: result.input_digest, resultHash: result.result_hash, ...evidenceIdentity(identity),
                        },
                    })),
                    quantileContract: Object.entries(result.quantile_contract ?? {}).map(([label, quantile]) => ({ label, quantile })),
                    quantileBasis: result.quantile_basis ?? null,
                    requestedSamples: result.requested_samples, validSamples: result.valid_samples, invalidSamples: result.invalid_samples,
                    invalidReasons: Object.entries(result.invalid_reasons ?? {}).map(([code, count]) => ({ code, count })),
                    seed: result.seed ?? null, samplerVersion: result.sampler_version ?? null, invalidDrawPolicy: result.invalid_draw_policy ?? null,
                    convergence: {
                        minimumValidSamples: result.convergence_diagnostics?.minimum_valid_samples ?? null,
                        invalidRatio: result.convergence_diagnostics?.invalid_ratio == null ? null : exactNumber(result.convergence_diagnostics.invalid_ratio),
                        converged: result.convergence_diagnostics?.converged ?? null,
                    },
                    sensitivity: Object.entries(result.sensitivity ?? {}).map(([path, values]) => ({ path, values: values.map(exactNumber) })),
                    dominantDrivers: result.dominant_drivers,
                    scenarios: result.scenario_results.map((scenario, index) => calculationModel(scenario, currency, identity, `scenario:${index}`)),
                    evidenceReferences: result.artifact_references,
                } : { kind: 'not-requested' },
            };
        }
        default: { const exhaustive: never = artifact; return exhaustive; }
    }
}
