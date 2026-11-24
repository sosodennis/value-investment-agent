import type { components } from '@/types/generated/api-contract';
import type { AnnualStatements } from '@/types/agents/annual-statements';
import type { ArtifactReference } from '@/types/agents';
import type { EvidenceSelection } from '../../workspace-evidence-inspector';
import { formatReportNumber } from './fundamental-number-format';

type Contracts = components['schemas'];
type Period = Contracts['StatementColumnV1']['period'];
const STATEMENT_TITLES = {
    income_statement: 'Income statement', balance_sheet: 'Balance sheet', cash_flow: 'Cash flow statement',
};

export type AnnualStatementModel = ReturnType<typeof projectAnnualStatements>;

function periodLabel(period: Period): string {
    switch (period.kind) {
        case 'duration': return `${period.period_start} to ${period.period_end}`;
        case 'instant': return `As of ${period.instant}`;
        case 'unresolved': return `Reported end ${period.reported_period_end} · ${period.missing.reason}`;
    }
}

export function projectAnnualStatements({ response, reference, threadId, companyName, ticker }: {
    response: AnnualStatements; reference: ArtifactReference | null; threadId?: string | null;
    companyName: string; ticker: string;
}) {
    const statement = response.statements;
    const identity = {
        artifactId: reference?.artifact_id, artifactUrl: reference?.download_url, threadId: threadId ?? undefined,
        statementId: statement.statement_id, inputDigest: statement.input_digest,
        statementRelease: response.data_release_manifest_digest, statementCutoff: statement.cutoff_at,
    };
    const candidates = new Map(statement.candidate_evidence.map((item) => [item.fact.fact_id, item]));
    const tables = statement.tables.map((table) => ({
        kind: table.statement, title: STATEMENT_TITLES[table.statement],
        columns: table.columns.map((column) => ({
            id: column.period_id, label: column.fiscal_label, period: periodLabel(column.period),
            calendar: column.calendar.replaceAll('_', ' '), days: column.duration_days,
            coverage: statement.coverage.find((item) => item.statement === table.statement && item.period_id === column.period_id),
        })),
        rows: table.rows.map((row) => ({
            id: row.definition.row_id, label: row.definition.label,
            cells: row.cells.map((cell) => {
                const column = table.columns.find((item) => item.period_id === cell.period_id);
                const base: EvidenceSelection = {
                    ...identity, id: `${reference?.artifact_id ?? statement.statement_id}:statement:${cell.cell_id}`,
                    title: `${row.definition.label} · ${column?.fiscal_label ?? cell.period_id}`,
                    cellId: cell.cell_id, rowId: cell.row_id, periodId: cell.period_id,
                    period: column ? periodLabel(column.period) : cell.period_id,
                    value: '', dataQuality: cell.quality_status,
                    candidateFactIds: cell.candidate_fact_ids,
                    rejectedCandidates: cell.rejected_candidates.map((item) => `${item.candidate_id} · ${item.reason}`),
                };
                if (cell.status === 'unavailable') {
                    return {
                        id: cell.cell_id, kind: 'unavailable',
                        label: cell.missing.status.replaceAll('_', ' '), reason: cell.missing.reason,
                        evidence: {
                            ...base, value: `${cell.missing.status} · ${cell.missing.reason}`,
                            issueCodes: cell.issue_codes,
                            statementEvidence: JSON.stringify({ cell, candidate_evidence: cell.candidate_fact_ids.map((id) => candidates.get(id)).filter((item) => item !== undefined) }, null, 2),
                        },
                    };
                }
                const fact = cell.fact;
                const raw = fact.value;
                const selectedEvidence = candidates.get(fact.fact_id);
                const evidence: EvidenceSelection = {
                    ...base, value: raw,
                    displayValue: formatReportNumber(raw, { kind: 'money', currency: statement.scope.currency }),
                    selectedVersionId: cell.selected_version_id, selectionKind: cell.selection_kind,
                    rationale: cell.selection_reason, sourceReportPeriodEnd: cell.source_report_period_end,
                    factId: fact.fact_id, concept: fact.concept, contextId: fact.context.context_id,
                    accessionNumber: fact.accession_number ?? undefined, sourceUrl: fact.source.source_url,
                    source: `${fact.source.source_role} · ${fact.source.source_url}`, sourceHash: fact.source.content_hash,
                    capturedAt: fact.captured_at, availableAt: fact.available_at, filedAt: fact.filed_at ?? undefined,
                    parserVersion: fact.source.parser_version, taxonomyVersion: fact.taxonomy_version,
                    snapshotId: cell.snapshot_id, snapshotManifestDigest: cell.snapshot_manifest_digest,
                    mappingVersion: selectedEvidence?.mapping.mapping_version, mappingDigest: cell.mapping_digest,
                    unit: fact.unit, scale: fact.scale, cashBasis: cell.cash_basis ?? undefined,
                    dimensions: fact.context.dimensions.map((item) => `${item.name}: ${item.member}`),
                    issueCodes: fact.issue_codes,
                    period: fact.context.period_type === 'instant' ? `As of ${fact.context.instant}` : `${fact.context.start_date} to ${fact.context.end_date}`,
                    statementEvidence: JSON.stringify({ cell, candidate_evidence: cell.candidate_fact_ids.map((id) => candidates.get(id)).filter((item) => item !== undefined) }, null, 2),
                };
                return { id: cell.cell_id, kind: 'reported', label: evidence.displayValue ?? raw, reason: cell.selection_kind.replaceAll('_', ' '), evidence };
            }),
        })),
        reconciliations: statement.reconciliations.filter((item) => item.statement === table.statement).map((item) => ({
            ...item,
            periodLabel: table.columns.find((column) => column.period_id === item.period_id)?.fiscal_label ?? item.period_id,
        })),
    }));
    const periodLabels = new Map(tables.flatMap((table) => table.columns.map((column) => [column.id, column.label] satisfies readonly [string, string])));
    return {
        companyName, ticker, issuerId: statement.scope.issuer_id, securityScope: statement.scope.security_scope,
        currency: statement.scope.currency, unit: statement.scope.unit,
        cutoffAt: statement.cutoff_at, statementId: statement.statement_id, releaseDigest: response.data_release_manifest_digest,
        profileId: statement.profile.profile_id, profileDigest: statement.profile.executable_digest,
        quality: statement.quality_status, targetYears: statement.profile.history_coverage_target,
        tables, evidence: tables.flatMap((table) => table.rows.flatMap((row) => row.cells.map((cell) => cell.evidence))),
        sourceOutcomes: statement.source_outcomes,
        comparability: statement.comparability.map((item) => ({
            ...item, earlier: periodLabels.get(item.earlier_period_id) ?? item.earlier_period_id,
            later: periodLabels.get(item.later_period_id) ?? item.later_period_id,
        })),
    };
}
