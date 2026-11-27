import type { components } from '@/types/generated/api-contract';
import type { ArtifactReference } from '@/types/agents';
import type { EvidenceSelection } from '../../workspace-evidence-inspector';
import { formatReportNumber } from './fundamental-number-format';

type Contracts = components['schemas'];
type FiscalPeriod = Contracts['FiscalValueNodeV1']['period'];
export type FiscalStatementModel = ReturnType<typeof projectFiscalStatements>;

const TITLES = {
    income_statement: 'Income statement', balance_sheet: 'Balance sheet', cash_flow: 'Cash flow statement',
};

export function fiscalPeriodText(period: FiscalPeriod): string {
    return period.kind === 'instant' ? `As of ${period.instant}` : `${period.start} to ${period.end} · ${period.inclusive_days} days`;
}

export function projectFiscalStatements({ saved, reference, threadId }: {
    saved: Contracts['StatementReadArtifactV3']; reference: ArtifactReference; threadId: string;
}) {
    if (saved.read.kind !== 'fiscal') throw new TypeError('A fiscal read is required.');
    const { result, result_digest: resultDigest, request } = saved.read;
    const { binding, evidence: graph } = result;
    const nodes = Object.fromEntries(graph.nodes.map((node) => [node.node_id, node]));
    const sources = Object.fromEntries(graph.source_uses.map((source) => [source.source_validation_ref.artifact_id, source]));
    const observationIds = new Set(graph.observations.map((observation) => observation.observation_id));
    const labels = Object.fromEntries(result.rows.map(({ row }) => [row.row_id, row.label]));
    const id = (key: string) => `${reference.artifact_id}:fiscal:${key}`;
    const identity = {
        artifactId: reference.artifact_id, artifactUrl: reference.download_url, threadId,
        statementRelease: binding.manifest_digest, statementCutoff: binding.cutoff_at,
        resultHash: resultDigest, inputDigest: binding.projection_digest,
        editionId: saved.edition.edition_id,
    };
    const parentLinks = (key: string): NonNullable<EvidenceSelection['evidenceLinks']> => graph.nodes.flatMap((parent) => {
        const references = [...parent.input_edges, ...parent.verification_edges].some((edge) => edge.input_id === key)
            || [...parent.source_observation_ids, ...parent.verification_observation_ids, ...parent.verification_node_ids].includes(key);
        return references ? [{ id: id(parent.node_id), label: `${labels[parent.row_id] ?? parent.row_id} · ${parent.frequency} · ${fiscalPeriodText(parent.period)}`, relationship: 'parent' }] : [];
    });
    const nodeItems: EvidenceSelection[] = graph.nodes.map((node) => ({
        ...identity, id: id(node.node_id), title: `${labels[node.row_id] ?? node.row_id} · ${node.frequency} · ${fiscalPeriodText(node.period)}`,
        value: node.value ?? `${node.availability} · ${node.reason_code ?? 'No reason supplied'}`,
        ...(node.value === null ? {} : { displayValue: formatReportNumber(node.value, { kind: 'money', currency: binding.scope.currency }) }),
        dataQuality: node.quality, selectionKind: node.availability, rowId: node.row_id,
        cellId: node.node_id, period: fiscalPeriodText(node.period),
        formula: node.formula ?? undefined, formulaVersion: `${node.policy_id} · ${node.executable_digest}`,
        rationale: node.reason_code ?? undefined, issueCodes: node.reason_code ? [node.reason_code] : [],
        sourceBindingDigest: node.source_binding_digest, unit: node.reporting_basis?.unit,
        cashBasis: node.reporting_basis?.cash_basis ?? undefined,
        availableAt: node.available_at ?? undefined,
        rejectedCandidates: node.candidates.filter((candidate) => candidate.outcome !== 'selected').map((candidate) => `${candidate.observation_id} · ${candidate.outcome} · ${candidate.reason}`),
        dimensions: node.reporting_basis?.dimensions.map(([name, member]) => `${name}: ${member}`),
        evidenceLinks: [
            ...node.input_edges.map((edge) => ({ id: id(edge.input_id), label: edge.input_id, coefficient: edge.coefficient, relationship: 'input' })),
            ...node.verification_edges.map((edge) => ({ id: id(edge.input_id), label: edge.input_id, coefficient: edge.coefficient, relationship: 'verification' })),
            ...node.source_observation_ids.map((key) => ({ id: id(key), label: key, relationship: 'reported source' })),
            ...node.verification_node_ids.map((key) => ({ id: id(key), label: key, relationship: 'verification' })),
            ...node.verification_observation_ids.map((key) => ({ id: id(key), label: key, relationship: 'verification source' })),
            ...node.candidates.filter((candidate) => observationIds.has(candidate.observation_id)).map((candidate) => ({ id: id(candidate.observation_id), label: `${candidate.outcome} · ${candidate.reason}`, relationship: 'candidate' })),
            ...parentLinks(node.node_id),
        ],
        statementEvidence: JSON.stringify(node, null, 2),
    }));
    const observationItems: EvidenceSelection[] = graph.observations.map((observation) => {
        const source = sources[observation.source_artifact_id];
        const period = observation.period.kind === 'reported_instant' ? `As of ${observation.period.instant}`
            : observation.period.kind === 'unsupported_duration' ? `${observation.period.start} to ${observation.period.end} · ${observation.period.reason}`
                : fiscalPeriodText(observation.period.period);
        return {
            ...identity, id: id(observation.observation_id),
            title: `${labels[observation.row_id] ?? observation.row_id} · ${observation.period.kind.replaceAll('_', ' ')} · ${period}`,
            value: observation.value ?? 'Unavailable', rawText: observation.raw_text,
            ...(observation.value === null ? {} : { displayValue: formatReportNumber(observation.value, { kind: 'money', currency: observation.basis.currency }) }),
            selectionKind: observation.period.kind, dataQuality: observation.quality,
            source: `${observation.form} · ${observation.accession_number} · ${observation.filing_revision.kind}`,
            sourceUrl: source.source_document.primary_document_url,
            sourceHash: source.source_document.primary_document_sha256,
            archiveMemberHash: source.source_document.archive_member_sha256,
            sourceBindingDigest: observation.source_binding_digest,
            accessionNumber: observation.accession_number, sourceReportPeriodEnd: observation.report_date,
            period, factId: observation.observation_id, concept: `${observation.namespace_uri} · ${observation.concept}`,
            contextId: observation.source_locator.context_id, unit: observation.basis.unit,
            scale: observation.scale, sign: observation.sign ?? 'Unspecified',
            decimals: observation.decimals === null ? 'Unspecified' : String(observation.decimals),
            mappingDigest: observation.mapping_digest,
            filedAt: observation.accepted_at, availableAt: observation.available_at,
            dimensions: observation.basis.dimensions.map(([name, member]) => `${name}: ${member}`),
            cashBasis: observation.basis.cash_basis ?? undefined,
            evidenceLinks: parentLinks(observation.observation_id),
            statementEvidence: JSON.stringify({ observation, source_inspection: source }, null, 2),
        };
    });
    const evidence = [...nodeItems, ...observationItems];
    const items = Object.fromEntries(evidence.map((item) => [item.id, item]));
    const columns = binding.columns.frequency === 'quarter'
        ? binding.columns.periods.map((period) => ({ id: period.period_id, quarters: [period] }))
        : binding.columns.windows.map((window) => ({ id: window.window_id, quarters: window.quarters }));
    const tables = Object.entries(TITLES).map(([kind, title]) => {
        const rows = result.rows.filter(({ row }) => row.statement === kind).map(({ row, cells }) => ({
            id: row.row_id, label: row.label, aggregation: row.aggregation,
            cells: cells.map((cell, index) => ({
                id: `${row.row_id}:${columns[index].id}`, kind: cell.kind,
                periodId: columns[index].id, node: nodes[cell.node_id], evidence: items[id(cell.node_id)],
                reason: cell.kind === 'reported' || cell.kind === 'derived' ? cell.kind : cell.reason_code.replaceAll('_', ' '),
            })),
        }));
        return {
            kind, title, rows,
            columns: columns.map((column, index) => {
                const period = rows[0]?.cells[index].node.period;
                return {
                    id: column.id, period,
                    label: period ? `${period.fiscal_year} · ${period.fiscal_period}` : column.id,
                    quarters: column.quarters,
                    reported: rows.filter((row) => row.cells[index].kind === 'reported').length,
                    derived: rows.filter((row) => row.cells[index].kind === 'derived').length,
                    unavailable: rows.filter((row) => row.cells[index].kind === 'unavailable').length,
                    conflict: rows.filter((row) => row.cells[index].kind === 'conflict').length,
                };
            }),
        };
    });
    return {
        companyName: saved.edition.company_name, ticker: saved.edition.ticker, editionLabel: saved.edition.label,
        frequency: request.frequency, scope: binding.scope, cutoffAt: binding.cutoff_at,
        releaseDigest: binding.manifest_digest, resultDigest, columns, tables, evidence,
        reconciliations: graph.reconciliations, cashContinuities: graph.cash_continuities,
        approved: binding.approved, selectedPeriodSetDigest: binding.selected_period_set_digest,
    };
}
