import type { components } from '@/types/generated/api-contract';
import { parseFundamentalCanonicalFact } from './fundamental-service-facts';
import { object, text, nonEmpty, boolean, integer, nullValue, optional, literal, union, array, dictionary, json, decimal, digest, date, timestamp, type Parser } from './fundamental-parser-primitives';

type Contracts = components['schemas'];
export type AnnualStatements = Contracts['AnnualStatementsReadResponseV1'];

function constant<const T extends string | number | null>(expected: T): Parser<T> {
    return (value, context) => {
        if (value !== expected) throw new TypeError(`${context} must be ${String(expected)}.`);
        return expected;
    };
}
const stringPair: Parser<[string, string]> = (value, context) => {
    if (!Array.isArray(value) || value.length !== 2) throw new TypeError(`${context} must be a string pair.`);
    return [text(value[0], context), text(value[1], context)];
};
const parseStatementScopeV1 = object<Contracts['StatementScopeV1']>({
    issuer_id: nonEmpty,
    security_id: union(text, nullValue),
    security_scope: text,
    entity_scope: text,
    currency: text,
    unit: text,
    consolidation_scope: constant("consolidated"),
});

const parseStatementRowDefinitionV1 = object<Contracts['StatementRowDefinitionV1']>({
    row_id: literal("revenue", "cost_of_revenue", "gross_profit", "operating_income", "income_before_tax", "income_tax_expense", "net_income", "cash_and_equivalents", "operating_current_receivables", "inventory", "current_assets", "property_plant_and_equipment", "total_assets", "operating_current_payables", "current_liabilities", "total_liabilities", "total_equity", "liabilities_and_equity", "operating_cash_flow", "investing_cash_flow", "financing_cash_flow", "effect_of_exchange_rates_on_cash", "net_change_in_cash", "cash_flow_beginning_balance", "cash_flow_ending_balance"),
    statement: literal("income_statement", "balance_sheet", "cash_flow"),
    label: text,
    value_period_role: literal("duration", "period_end", "day_before_period_start"),
    concepts: array(text),
    sign_policy: constant("reported_signed_decimal_v1"),
});

const parseStatementProfileV1 = object<Contracts['StatementProfileV1']>({
    profile_id: constant("us-gaap-nonfinancial-annual-v1"),
    contract_version: constant("fundamental.annual-statements.v1"),
    rows: array(parseStatementRowDefinitionV1),
    selection_policy: constant("canonical-pit-exact-row-key-v1"),
    reconciliation_policy: constant("reported-decimals-half-unit-sum-v1"),
    comparability_policy: constant("actual-annual-periods-no-annualization-v1"),
    executable_digest: digest,
    history_coverage_target: constant(5),
    supported_history_threshold: optional(nullValue),
});

const parseDurationStatementPeriodV1 = object<Contracts['DurationStatementPeriodV1']>({
    kind: constant("duration"),
    period_start: date,
    period_end: date,
});

const parseInstantStatementPeriodV1 = object<Contracts['InstantStatementPeriodV1']>({
    kind: constant("instant"),
    instant: date,
});

const parseFundamentalMissingValueV1 = object<Contracts['FundamentalMissingValueV1']>({
    status: literal("missing", "not_applicable", "unsupported", "unresolved"),
    reason: nonEmpty,
});

const parseStatementArtifactRefV1 = object<Contracts['StatementArtifactRefV1']>({
    artifact_id: nonEmpty,
    content_hash: digest,
    media_type: nonEmpty,
    role: nonEmpty,
});

const parseUnresolvedStatementPeriodV1 = object<Contracts['UnresolvedStatementPeriodV1']>({
    kind: constant("unresolved"),
    reported_period_end: date,
    missing: parseFundamentalMissingValueV1,
    source_outcome_ref: parseStatementArtifactRefV1,
});

const parseStatementColumnV1 = object<Contracts['StatementColumnV1']>({
    period_id: digest,
    fiscal_label: text,
    period: union(parseDurationStatementPeriodV1, union(parseInstantStatementPeriodV1, parseUnresolvedStatementPeriodV1)),
    duration_days: union(integer, nullValue),
    calendar: literal("52_week", "53_week", "calendar_year", "other", "unresolved"),
});

const parseFundamentalCandidateRejectionV1 = object<Contracts['FundamentalCandidateRejectionV1']>({
    candidate_id: nonEmpty,
    reason: nonEmpty,
});

const parseStatementNumericFact: Parser<Contracts['StatementNumericFactV1']> = (value, context) => {
    const fact = parseFundamentalCanonicalFact(value, context);
    return { ...fact, value: decimal(fact.value, `${context}.value`) };
};

const parseReportedStatementCellV1 = object<Contracts['ReportedStatementCellV1']>({
    status: constant("reported"),
    cell_id: digest,
    row_id: literal("revenue", "cost_of_revenue", "gross_profit", "operating_income", "income_before_tax", "income_tax_expense", "net_income", "cash_and_equivalents", "operating_current_receivables", "inventory", "current_assets", "property_plant_and_equipment", "total_assets", "operating_current_payables", "current_liabilities", "total_liabilities", "total_equity", "liabilities_and_equity", "operating_cash_flow", "investing_cash_flow", "financing_cash_flow", "effect_of_exchange_rates_on_cash", "net_change_in_cash", "cash_flow_beginning_balance", "cash_flow_ending_balance"),
    period_id: digest,
    selected_version_id: digest,
    fact: parseStatementNumericFact,
    snapshot_id: text,
    snapshot_manifest_digest: digest,
    mapping_digest: digest,
    mapping_evidence_refs: array(parseStatementArtifactRefV1),
    cash_basis: union(literal("cash_and_equivalents", "cash_equivalents_and_restricted_cash"), nullValue),
    selection_reason: text,
    selection_kind: literal("original", "amended", "later_comparative"),
    source_report_period_end: date,
    candidate_fact_ids: array(text),
    rejected_candidates: array(parseFundamentalCandidateRejectionV1),
    quality_status: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
});

const parseUnavailableStatementCellV1 = object<Contracts['UnavailableStatementCellV1']>({
    status: constant("unavailable"),
    cell_id: digest,
    row_id: literal("revenue", "cost_of_revenue", "gross_profit", "operating_income", "income_before_tax", "income_tax_expense", "net_income", "cash_and_equivalents", "operating_current_receivables", "inventory", "current_assets", "property_plant_and_equipment", "total_assets", "operating_current_payables", "current_liabilities", "total_liabilities", "total_equity", "liabilities_and_equity", "operating_cash_flow", "investing_cash_flow", "financing_cash_flow", "effect_of_exchange_rates_on_cash", "net_change_in_cash", "cash_flow_beginning_balance", "cash_flow_ending_balance"),
    period_id: digest,
    missing: parseFundamentalMissingValueV1,
    quality_status: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
    issue_codes: array(text),
    evidence_refs: array(parseStatementArtifactRefV1),
    candidate_fact_ids: array(text),
    rejected_candidates: array(parseFundamentalCandidateRejectionV1),
});

const parseStatementRowV1 = object<Contracts['StatementRowV1']>({
    definition: parseStatementRowDefinitionV1,
    cells: array(union(parseReportedStatementCellV1, parseUnavailableStatementCellV1)),
});

const parseStatementTableV1 = object<Contracts['StatementTableV1']>({
    statement: literal("income_statement", "balance_sheet", "cash_flow"),
    columns: array(parseStatementColumnV1),
    rows: array(parseStatementRowV1),
});

const parseStatementAvailableSourceV1 = object<Contracts['StatementAvailableSourceV1']>({
    kind: constant("available"),
    accession_number: text,
    available_at: timestamp,
    report_period_end: date,
    outcome_ref: parseStatementArtifactRefV1,
    fact_ids: array(text),
});

const parseStatementUnavailableSourceV1 = object<Contracts['StatementUnavailableSourceV1']>({
    kind: constant("unavailable"),
    accession_number: text,
    available_at: timestamp,
    report_period_end: date,
    outcome_ref: parseStatementArtifactRefV1,
    quality_status: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
    missing: parseFundamentalMissingValueV1,
    issue_codes: array(text),
});

const parseStatementMappingV1 = object<Contracts['StatementMappingV1']>({
    contract_version: constant("fundamental.v1"),
    decision_id: text,
    source_concept: text,
    normalized_field: text,
    mapping_version: text,
    anchor_concept: optional(union(text, nullValue)),
    confidence: literal("high", "medium", "low", "unresolved"),
    evidence_refs: array(text),
    reviewer: optional(union(text, nullValue)),
    reviewed_at: optional(union(timestamp, nullValue)),
    status: literal("approved", "provisional", "ambiguous", "rejected"),
    security_scope: optional(union(literal("issuer"), nullValue)),
    accounting_rules: optional(union(dictionary(json), nullValue)),
    observation_scope: optional(union(dictionary(json), nullValue)),
});

const parseStatementSourceRecordV1 = object<Contracts['StatementSourceRecordV1']>({
    source_id: text,
    uri: text,
    role: literal("filing", "company_facts", "taxonomy", "acquisition", "macro", "market", "reference"),
    available_at: timestamp,
    captured_at: timestamp,
    publication_at: optional(union(timestamp, nullValue)),
    http_status: integer,
    media_type: text,
    terms_reference: text,
    content_hash: digest,
    parser_input_hash: optional(union(text, nullValue)),
    parser_version: text,
    accession_number: optional(union(text, nullValue)),
    form: optional(union(text, nullValue)),
    filing_date: optional(union(date, nullValue)),
    filed_at: optional(union(timestamp, nullValue)),
    filing_version: optional(union(text, nullValue)),
    is_amendment: boolean,
    amends_accession: optional(union(text, nullValue)),
    supersedes_accession: optional(union(text, nullValue)),
    amendment_scope: optional(union(literal("valuation_relevant", "unrelated", "unknown"), nullValue)),
    taxonomy_manifest_id: optional(union(text, nullValue)),
    response_headers: array(stringPair),
    declared_size: optional(union(integer, nullValue)),
    received_size: optional(union(integer, nullValue)),
    point_in_time_relevant: boolean,
});

const parseStatementFactEvidenceV1 = object<Contracts['StatementFactEvidenceV1']>({
    fact: parseFundamentalCanonicalFact,
    mapping: parseStatementMappingV1,
    source: parseStatementSourceRecordV1,
    snapshot_id: nonEmpty,
    snapshot_manifest_digest: digest,
    mapping_evidence_refs: array(parseStatementArtifactRefV1),
    cash_basis: optional(union(literal("cash_and_equivalents", "cash_equivalents_and_restricted_cash"), nullValue)),
});

const parseStatementCoverageV1 = object<Contracts['StatementCoverageV1']>({
    period_id: digest,
    statement: literal("income_statement", "balance_sheet", "cash_flow"),
    fiscal_label: text,
    reported_rows: integer,
    declared_rows: integer,
    unavailable_row_ids: array(literal("revenue", "cost_of_revenue", "gross_profit", "operating_income", "income_before_tax", "income_tax_expense", "net_income", "cash_and_equivalents", "operating_current_receivables", "inventory", "current_assets", "property_plant_and_equipment", "total_assets", "operating_current_payables", "current_liabilities", "total_liabilities", "total_equity", "liabilities_and_equity", "operating_cash_flow", "investing_cash_flow", "financing_cash_flow", "effect_of_exchange_rates_on_cash", "net_change_in_cash", "cash_flow_beginning_balance", "cash_flow_ending_balance")),
});

const parseStatementComparabilityV1 = object<Contracts['StatementComparabilityV1']>({
    earlier_period_id: digest,
    later_period_id: digest,
    status: literal("comparable", "limited", "not_comparable"),
    issue_codes: array(text),
    affected_row_ids: array(literal("revenue", "cost_of_revenue", "gross_profit", "operating_income", "income_before_tax", "income_tax_expense", "net_income", "cash_and_equivalents", "operating_current_receivables", "inventory", "current_assets", "property_plant_and_equipment", "total_assets", "operating_current_payables", "current_liabilities", "total_liabilities", "total_equity", "liabilities_and_equity", "operating_cash_flow", "investing_cash_flow", "financing_cash_flow", "effect_of_exchange_rates_on_cash", "net_change_in_cash", "cash_flow_beginning_balance", "cash_flow_ending_balance")),
});

const parseStatementReconciliationV1 = object<Contracts['StatementReconciliationV1']>({
    statement: literal("income_statement", "balance_sheet", "cash_flow"),
    period_id: digest,
    check_id: text,
    status: literal("passed", "rounding", "unresolved", "not_applicable", "failed"),
    severity: literal("info", "warning", "error", "fatal"),
    expression: text,
    input_fact_ids: array(text),
    difference: union(decimal, nullValue),
    tolerance: union(decimal, nullValue),
    issue_codes: array(text),
    policy_version: constant("reported-decimals-half-unit-sum-v1"),
});

const parseAnnualStatementsV1 = object<Contracts['AnnualStatementsV1']>({
    contract_version: constant("fundamental.annual-statements.v1"),
    statement_id: digest,
    input_digest: digest,
    scope: parseStatementScopeV1,
    cutoff_at: timestamp,
    profile: parseStatementProfileV1,
    tables: array(parseStatementTableV1),
    source_outcomes: array(union(parseStatementAvailableSourceV1, parseStatementUnavailableSourceV1)),
    candidate_evidence: array(parseStatementFactEvidenceV1),
    coverage: array(parseStatementCoverageV1),
    comparability: array(parseStatementComparabilityV1),
    reconciliations: array(parseStatementReconciliationV1),
    quality_status: literal("verified", "provisional", "degraded", "unsupported", "abstain", "error"),
    valuation_eligibility: constant("not_evaluated"),
});

const parseAnnualStatementsReadResponseV1 = object<Contracts['AnnualStatementsReadResponseV1']>({
    contract_version: constant("fundamental.annual-statements.v1"),
    data_release_manifest_digest: digest,
    statements: parseAnnualStatementsV1,
});
export function parseAnnualStatements(value: unknown, context = 'annual statements'): AnnualStatements {
    const parsed = parseAnnualStatementsReadResponseV1(value, context);
    const statement = parsed.statements;
    const candidateIds = new Set(statement.candidate_evidence.map((item) => item.fact.fact_id));
    const cellIds = new Set<string>();
    const statementKinds = new Set<string>();
    const periodIds = new Set<string>();
    for (const table of statement.tables) {
        if (statementKinds.has(table.statement)) throw new TypeError(`${context} has duplicate statements.`);
        statementKinds.add(table.statement);
        const periods = table.columns.map((column) => column.period_id);
        if (new Set(periods).size !== periods.length) throw new TypeError(`${context} has duplicate periods.`);
        periods.forEach((id) => periodIds.add(id));
        for (const row of table.rows) {
            if (row.definition.statement !== table.statement || row.cells.length !== periods.length) throw new TypeError(`${context} has a misaligned statement row.`);
            row.cells.forEach((cell, index) => {
                if (cell.row_id !== row.definition.row_id || cell.period_id !== periods[index] || cellIds.has(cell.cell_id)) throw new TypeError(`${context} has a misaligned or duplicate cell.`);
                cellIds.add(cell.cell_id);
                if (cell.status === 'reported') {
                    const fact = cell.fact;
                    decimal(fact.value, `${context}.cell.value`);
                    if (fact.issuer_id !== statement.scope.issuer_id || fact.normalized_field !== cell.row_id || Date.parse(fact.available_at) > Date.parse(statement.cutoff_at)) throw new TypeError(`${context} has a fact outside its issuer or cutoff.`);
                    if (!candidateIds.has(fact.fact_id) || !cell.candidate_fact_ids.includes(fact.fact_id)) throw new TypeError(`${context} lacks selected candidate evidence.`);
                    if (fact.source.accession_number !== fact.accession_number || fact.context.concept_qname !== fact.concept) throw new TypeError(`${context} has inconsistent source evidence.`);
                }
            });
        }
    }
    for (const item of [...statement.coverage, ...statement.reconciliations]) {
        if (!periodIds.has(item.period_id)) throw new TypeError(`${context} references an unknown period.`);
    }
    return parsed;
}
