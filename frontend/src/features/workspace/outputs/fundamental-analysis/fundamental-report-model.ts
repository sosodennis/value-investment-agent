import type { components } from '@/types/generated/api-contract';
import type { ArtifactReference } from '@/types/agents';
import { isFundamentalDecimalText, isRevisedFundamentalPreparation, type FundamentalServiceArtifact } from '@/types/agents/fundamental-service-facts';
import { getArtifactRunId } from '@/features/artifacts/api';
import type { EvidenceSelection } from '../../workspace-evidence-inspector';
import { assumptionNumberSemantic, factNumberSemantic, formatReportDatum, formatReportNumber, nodeNumberSemantic, type NumberSemantic, type ReportDatum } from './fundamental-number-format';

type Contracts = components['schemas'];
type Calculation = Contracts['FundamentalCalculationResultV1'];
type Fact = Contracts['FundamentalCanonicalFactV1'];
type Quality = Calculation['quality_status'];
type Binding = { inputDigest: string; resultHash: string };
type AssumptionRevisionLabel = 'Original retained assumption' | 'Applied manual assumption' | 'Manual assumption · application unconfirmed';

export type ExactNumber = { raw: string; coordinate: number | null };
export type ExactAmount = ExactNumber & { currency: string; basis: 'equity-total' | 'per-share'; evidence: EvidenceSelection };
export type FundamentalReportIdentity = {
    threadId: string | null;
    runId: string | null;
    artifactId: string | null;
    artifactUrl: string | null;
    preparationDigest: string | null;
};
export type FundamentalFactModel = {
    id: string;
    normalizedField: string;
    label: string;
    value: ReportDatum;
    period: string;
    context: {
        issuerId: string; securityId: string | null; securityScope: string | null; entityScope: string; consolidationScope: string;
        periodType: 'instant' | 'duration'; start: string | null; end: string;
        unitQname: string; measure: string; conceptQname: string;
        accession: string | null; filingVersion: string | null; isAmendment: boolean;
        amendsAccession: string | null; supersedesAccession: string | null;
        amendmentScope: 'valuation_relevant' | 'unrelated' | 'unknown' | null;
    };
    unit: string;
    scale: number;
    currency: string | null;
    dimensions: { name: string; member: string }[];
    quality: Quality;
    issueCodes: string[];
    evidence: EvidenceSelection;
};
type CalculationModel = {
    assumptionsJson: string;
    binding: Binding;
    status: Calculation['calculation_status'];
    quality: Quality;
    equity: ExactAmount | null;
    perShare: ExactAmount | null;
    evaluatedAt: string;
    valuationDate: string;
    issueCodes: string[];
    missingEvidence: string[];
    nodes: { id: string; value: ExactNumber | null; semantic: NumberSemantic; unit: string; formula: string; inputs: string[]; evidence: EvidenceSelection }[];
    evidenceReferences: Contracts['FundamentalServiceEvidenceReferenceV1'][];
};
export type CapitalCompleteness =
    | { kind: 'not-supplied' }
    | { kind: 'provided'; completeClaims: boolean | null; completeAwards: boolean | null; unknowns: string[]; limitations: string[] };

export type PreparationSummary = {
    digest: string;
    canApplyResearch: boolean;
    capitalCompleteness: CapitalCompleteness;
    status: Contracts['FundamentalValuationPreparationResultV1']['status'];
    modelId: Contracts['FundamentalValuationPreparationResultV1']['model_id'];
    modelVersion: string;
    policyId: string;
    policyVersion: string;
    quality: Quality;
    isRevised: boolean;
    issueCodes: string[];
    missingEvidence: string[];
    assumptions: { path: string; value: ExactNumber; semantic: NumberSemantic; method: string; editable: boolean; isManual: boolean; originalPreparationDigest: string | null; revisionLabel: AssumptionRevisionLabel | null; formula: string; evidence: EvidenceSelection }[];
    historicalMetrics: { id: string; year: number; value: ExactNumber; semantic: NumberSemantic; evidence: EvidenceSelection; unit: string; periodEnd: string; formula: string; factIds: string[] }[];
};
type UncertaintyModel = {
    kind: 'provided';
    mode: 'sampled' | 'scenarios';
    binding: Binding;
    quality: Quality;
    quantiles: { label: string; aliasOf: string | null; value: ExactAmount; evidence: EvidenceSelection }[];
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
    ticker: string;
    issuerId: string | null;
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
        items.push(...(report.preparationSummary?.historicalMetrics.map((item) => item.evidence) ?? []));
    }
    if (report.kind === 'valuation') {
        if (report.base.perShare) items.push(report.base.perShare.evidence);
        if (report.base.equity) items.push(report.base.equity.evidence);
        items.push(...report.base.nodes.map((node) => node.evidence));
        if (report.uncertainty.kind === 'provided') {
            items.push(...report.uncertainty.quantiles.map((quantile) => quantile.evidence));
            items.push(...report.uncertainty.scenarios.flatMap((scenario) => scenario.nodes.map((node) => node.evidence)));
            for (const scenario of report.uncertainty.scenarios) {
                if (scenario.perShare) items.push(scenario.perShare.evidence);
                if (scenario.equity) items.push(scenario.equity.evidence);
            }
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

function amount(raw: string | null | undefined, currency: string, basis: ExactAmount['basis'], result: Calculation, identity: FundamentalReportIdentity, scope: string): ExactAmount | null {
    if (raw == null) return null;
    const node = result.nodes.find((item) => item.node_id === (basis === 'per-share' ? 'per_share_value' : 'equity_value'));
    const semantic: NumberSemantic = { kind: basis === 'per-share' ? 'per-share' : 'money', currency };
    const title = `${scope === 'base' ? 'Deterministic base' : `Service scenario ${scope.slice('scenario:'.length)}`} ${basis === 'per-share' ? 'per share' : 'total equity value'}`;
    return {
        ...exactNumber(raw), currency, basis,
        evidence: {
            id: evidenceKey(identity, 'result', `${scope}:${result.result_hash}:${basis}`), title,
            value: raw, displayValue: formatReportNumber(raw, semantic), unit: `${currency}${basis === 'per-share' ? ' / share' : ''}`,
            formula: node?.formula, inputs: node?.inputs, period: result.valuation_timestamp,
            source: result.artifact_references.map((item) => `${item.artifact_type} · ${item.artifact_id}`).join(', '),
            dataQuality: result.quality_status, inputDigest: result.input_digest, resultHash: result.result_hash,
            ...evidenceIdentity(identity),
        },
    };
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
    const value: ReportDatum = typeof fact.value === 'string' ? isFundamentalDecimalText(fact.value)
        ? { kind: 'number', raw: fact.value, semantic: factNumberSemantic(fact.normalized_field, fact.currency ?? null, fact.unit) }
        : { kind: 'text', value: fact.value }
        : typeof fact.value === 'boolean' ? { kind: 'boolean', value: fact.value }
            : { kind: 'unavailable', status: fact.value.status, reason: fact.value.reason };
    const rawValue = value.kind === 'number' ? value.raw : value.kind === 'boolean' || value.kind === 'text' ? String(value.value) : `${value.status}: ${value.reason}`;
    const period = fact.context.period_type === 'instant'
        ? `Instant · ${fact.instant ?? fact.context.instant ?? fact.period_end}`
        : `${fact.period_start ?? fact.context.start_date ?? 'Start unavailable'} → ${fact.period_end}`;
    return {
        id: fact.fact_id, normalizedField: fact.normalized_field, label, value, period,
        context: {
            issuerId: fact.issuer_id, securityId: fact.security_id ?? null, securityScope: fact.security_scope ?? null, entityScope: fact.context.entity_scope, consolidationScope: fact.context.consolidation_scope,
            periodType: fact.context.period_type, start: fact.period_start ?? fact.context.start_date ?? null,
            end: fact.instant ?? fact.context.instant ?? fact.period_end,
            unitQname: fact.context.unit_qname, measure: fact.context.measure, conceptQname: fact.context.concept_qname,
            accession: fact.accession_number ?? fact.source.accession_number ?? null, filingVersion: fact.filing_version ?? null,
            isAmendment: fact.is_amendment, amendsAccession: fact.amends_accession ?? null,
            supersedesAccession: fact.supersedes_accession ?? null, amendmentScope: fact.amendment_scope ?? null,
        },
        unit: fact.unit, scale: fact.scale, currency: fact.currency ?? null,
        dimensions: fact.context.dimensions, quality: fact.quality, issueCodes: fact.issue_codes,
        evidence: {
            id: evidenceKey(identity, 'fact', fact.fact_id), title: `Service fact · ${label}`,
            value: rawValue, displayValue: formatReportDatum(value), period, source: `${fact.source.source_role} · ${fact.source.source_url}`,
            sourceUrl: fact.source.source_url, dataQuality: fact.quality, ...evidenceIdentity(identity),
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
        assumptionsJson: JSON.stringify(result.assumptions, null, 2),
        binding: binding(result), status: result.calculation_status, quality: result.quality_status,
        equity: amount(result.intrinsic_value, currency, 'equity-total', result, identity, scope),
        perShare: amount(result.per_share_value, currency, 'per-share', result, identity, scope),
        evaluatedAt: result.evaluated_at, valuationDate: result.valuation_timestamp,
        issueCodes: result.issue_codes, missingEvidence: result.missing_evidence,
        nodes: result.nodes.map((node) => ({
            id: node.node_id, value: node.value == null ? null : exactNumber(node.value),
            semantic: nodeNumberSemantic(node.node_id, node.unit, currency),
            unit: node.unit, formula: node.formula, inputs: node.inputs,
            evidence: {
                id: evidenceKey(identity, 'node', `${scope}:${result.result_hash}:${node.node_id}`), title: `Calculation · ${node.node_id}`,
                value: node.value ?? 'Unavailable', unit: node.unit,
                displayValue: node.value == null ? 'Unavailable' : formatReportNumber(node.value, nodeNumberSemantic(node.node_id, node.unit, currency)),
                formula: node.formula, source: [...node.trace.source_refs, ...node.trace.source_uris].join(', '),
                ...evidenceIdentity(identity),
                capturedAt: node.trace.captured_at ?? undefined, availableAt: node.trace.available_at ?? undefined,
                snapshotId: result.snapshot_id, dataQuality: result.quality_status,
                inputDigest: result.input_digest, resultHash: result.result_hash, inputs: node.inputs,
            },
        })),
        evidenceReferences: result.artifact_references,
    };
}

function capitalCompleteness(preparation: Contracts['FundamentalValuationPreparationResultV1']): CapitalCompleteness {
    const policy = preparation.conditional_capital?.policy;
    if (typeof policy !== 'object' || policy === null || Array.isArray(policy)) return { kind: 'not-supplied' };
    return {
        kind: 'provided',
        completeClaims: 'complete_capital_claims' in policy && typeof policy.complete_capital_claims === 'boolean' ? policy.complete_capital_claims : null,
        completeAwards: 'complete_award_inventory' in policy && typeof policy.complete_award_inventory === 'boolean' ? policy.complete_award_inventory : null,
        unknowns: 'unknowns' in policy && Array.isArray(policy.unknowns) ? policy.unknowns.filter((item): item is string => typeof item === 'string') : [],
        limitations: 'limitations' in policy && Array.isArray(policy.limitations) ? policy.limitations.filter((item): item is string => typeof item === 'string') : [],
    };
}

function preparationSummary(preparation: Contracts['FundamentalValuationPreparationResultV1'], identity: FundamentalReportIdentity, currency: string): PreparationSummary {
    const hasManualTerminalGrowth = preparation.assumptions_evidence.some((item) => item.path === 'assumptions.terminal_growth' && (item.method === 'manual' || item.manual_provenance != null));
    const assumptions = preparation.input?.assumptions;
    const appliedTerminalGrowth = typeof assumptions === 'object' && assumptions !== null && !Array.isArray(assumptions) && 'terminal_growth' in assumptions
        ? assumptions.terminal_growth
        : undefined;
    return {
        digest: preparation.preparation_digest, status: preparation.status,
        capitalCompleteness: capitalCompleteness(preparation),
        canApplyResearch: preparation.conditional_capital != null || preparation.conditional_operating != null,
        modelId: preparation.model_id, modelVersion: preparation.model_version,
        policyId: preparation.policy_id, policyVersion: preparation.policy_version,
        quality: preparation.quality_status, isRevised: isRevisedFundamentalPreparation(preparation), issueCodes: preparation.issue_codes, missingEvidence: preparation.missing_evidence,
        assumptions: preparation.assumptions_evidence.map((item, index) => {
            const isManual = item.method === 'manual' || item.manual_provenance != null;
            const revisionLabel: AssumptionRevisionLabel | null = item.path !== 'assumptions.terminal_growth' || !hasManualTerminalGrowth
                ? null
                : !isManual
                    ? 'Original retained assumption'
                    : typeof appliedTerminalGrowth === 'string' && item.value === appliedTerminalGrowth
                        ? 'Applied manual assumption'
                        : 'Manual assumption · application unconfirmed';
            return {
                path: item.path, value: exactNumber(item.value), semantic: assumptionNumberSemantic(item.path, currency), method: item.method, editable: item.editable,
                isManual, originalPreparationDigest: item.manual_provenance?.automatic_preparation_digest ?? null, revisionLabel, formula: item.formula,
                evidence: {
                    id: evidenceKey(identity, 'assumption', `${item.path}:${index}`), title: `${revisionLabel ?? 'Assumption'} · ${item.path}`,
                    value: item.value, displayValue: formatReportNumber(item.value, assumptionNumberSemantic(item.path, currency)), formula: item.formula,
                    source: item.manual_provenance?.forward_reference?.source_url ?? item.source_refs.join(', '),
                    citation: item.manual_provenance?.forward_reference?.citation,
                    licenseReference: item.manual_provenance?.forward_reference?.license_reference,
                    sourceHash: item.manual_provenance?.forward_reference?.source_content_hash,
                    author: item.manual_provenance?.author,
                    originalPreparationDigest: item.manual_provenance?.automatic_preparation_digest,
                    sourceUrl: item.manual_provenance?.forward_reference?.source_url,
                    modifiedAt: item.manual_provenance?.modified_at,
                    rationale: item.manual_provenance?.reason,
                    period: item.as_of, assumptionMethod: item.method, inputs: item.fact_ids, ...evidenceIdentity(identity),
                },
            };
        }),
        historicalMetrics: preparation.historical_metrics.metrics.map((metric, index) => {
            const semantic = nodeNumberSemantic(metric.metric_id, metric.unit, currency);
            return {
                id: metric.metric_id, year: metric.fiscal_year, value: exactNumber(metric.value), semantic,
                unit: metric.unit, periodEnd: metric.period_end, formula: metric.formula, factIds: metric.fact_ids,
                evidence: {
                    id: evidenceKey(identity, 'historical-metric', `${metric.metric_id}:${metric.fiscal_year}:${index}`),
                    title: `Historical metric · ${metric.metric_id} · FY${metric.fiscal_year}`,
                    value: metric.value, displayValue: formatReportNumber(metric.value, semantic), unit: metric.unit,
                    period: `FY${metric.fiscal_year} · period ending ${metric.period_end}`, formula: metric.formula,
                    source: metric.source_refs.join(', '), inputs: metric.fact_ids,
                    dataQuality: preparation.historical_metrics.quality_status, ...evidenceIdentity(identity),
                },
            };
        }),
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
        identity, ticker: companyIdentity?.security_id ?? ticker, issuerId: companyIdentity?.issuer_id ?? null, company: companyIdentity?.issuer_name ?? ticker, shareClass: companyIdentity?.share_class ?? null,
        currency: companyIdentity?.currency ?? null, quality: artifact.projection_type === 'facts_only' ? artifact.quality.facts_status : artifact.quality_status,
        issueCodes: artifact.projection_type === 'valuation' ? artifact.quality.issue_codes : artifact.issue_codes, facts,
    };
    switch (artifact.projection_type) {
        case 'degraded': return { ...common, kind: 'service-error', ...artifact.service_failure };
        case 'facts_only': return { ...common, kind: 'facts-only', snapshotId: artifact.snapshot_id, valuationDate: artifact.facts.valuation_timestamp };
        case 'preparation_outcome': return {
            ...common, kind: 'preparation-outcome', outcome: artifact.valuation_status,
            reason: artifact.reason ?? null, missingEvidence: artifact.missing_evidence,
            preparationSummary: preparationSummary(artifact.automatic_preparation, identity, common.currency ?? ''),
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
                preparationSummary: artifact.automatic_preparation == null ? null : preparationSummary(artifact.automatic_preparation, identity, currency),
                uncertainty: 'base' in result ? {
                    kind: 'provided', mode: result.requested_samples > 0 ? 'sampled' : 'scenarios', binding: binding(result), quality: result.status,
                    quantiles: Object.entries(result.quantiles ?? {}).map(([label, raw]) => {
                        const aliases = new Map([['lower', 'p05'], ['median', 'p50'], ['upper', 'p95']]);
                        const target = aliases.get(label);
                        const aliasOf = result.quantile_basis != null && result.quantile_contract?.bear === 'p05' && result.quantile_contract?.base === 'p50' && result.quantile_contract?.bull === 'p95'
                            && target && result.quantiles?.[target] === raw ? target : null;
                        const evidence: EvidenceSelection = {
                            id: evidenceKey(identity, 'quantile', label), title: `Model quantile · ${label}`,
                            value: raw, displayValue: formatReportNumber(raw, { kind: 'per-share', currency }), unit: `${currency} / share`, dataQuality: result.status, period: result.base.valuation_timestamp,
                            source: result.artifact_references.map((item) => `${item.artifact_type} · ${item.artifact_id}`).join(', '),
                            inputDigest: result.input_digest, resultHash: result.result_hash, ...evidenceIdentity(identity),
                        };
                        return { label, aliasOf, value: { ...exactNumber(raw), currency, basis: 'per-share', evidence } satisfies ExactAmount, evidence };
                    }),
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
                    scenarios: result.scenario_results.map((scenario, index) => calculationModel(scenario, currency, identity, `scenario:${index + 1}`)),
                    evidenceReferences: result.artifact_references,
                } : { kind: 'not-requested' },
            };
        }
        default: { const exhaustive: never = artifact; return exhaustive; }
    }
}
