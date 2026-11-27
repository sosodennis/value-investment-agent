import Ajv2020 from 'ajv/dist/2020';
import type { ErrorObject } from 'ajv';
import { customizeValidator } from '@rjsf/validator-ajv8';
import readSchema from '@/types/generated/statement-read-artifact.schema.v3.json';
import catalogSchema from '@/types/generated/statement-catalog.schema.v2.json';
import type { components } from '@/types/generated/api-contract';
import { parseAnnualStatements } from './annual-statements';
import { decimal } from './fundamental-parser-primitives';

type Contracts = components['schemas'];
type SavedRead = Contracts['StatementReadArtifactV3'];
const validator = customizeValidator<unknown>({
    AjvClass: Ajv2020,
    ajvOptionsOverrides: { allErrors: false, strict: false, useDefaults: false, coerceTypes: false },
});
const validateRead = validator.ajv.compile<SavedRead>(readSchema);
const validateCatalog = validator.ajv.compile<Contracts['StatementCatalogV2']>(catalogSchema);

function shapeError(context: string, errors: ErrorObject[] | null | undefined) {
    const error = errors?.[0];
    return new TypeError(`${context} violates the statement contract${error ? ` at ${error.instancePath || '/'}: ${error.message}` : '.'}`);
}

function scopeKey(scope: Contracts['StatementScopeV1']) {
    return JSON.stringify([scope.issuer_id, scope.security_id, scope.security_scope, scope.entity_scope, scope.currency, scope.unit, scope.consolidation_scope]);
}

export function statementEditionIdentity(edition: Contracts['StatementEditionV2']) {
    return JSON.stringify([edition.edition_id, scopeKey(edition.scope), edition.cutoff_at, edition.annual_manifest_digest, edition.fiscal_manifest_digest]);
}

export function parseStatementCatalog(value: unknown, context = 'statement catalog'): Contracts['StatementCatalogV2'] {
    if (!validateCatalog(value)) throw shapeError(context, validateCatalog.errors);
    const catalog = value;
    if (new Set(catalog.entries.map((entry) => entry.edition_id)).size !== catalog.entries.length) throw new TypeError(`${context} repeats an edition identity.`);
    return catalog;
}

export function parseStatementRead(value: unknown, context = 'statement read'): SavedRead {
    if (!validateRead(value)) throw shapeError(context, validateRead.errors);
    const saved = value;
    const { edition, read } = saved;
    if (read.kind === 'annual') {
        const response = parseAnnualStatements(read.response, `${context}.annual`);
        if (response.data_release_manifest_digest !== edition.annual_manifest_digest || scopeKey(response.statements.scope) !== scopeKey(edition.scope)
            || Date.parse(response.statements.cutoff_at) !== Date.parse(edition.cutoff_at)) throw new TypeError(`${context} differs from its saved annual edition.`);
        return saved;
    }
    const { request, result } = read;
    const { binding, evidence } = result;
    if (request.manifest_digest !== edition.fiscal_manifest_digest || request.manifest_digest !== binding.manifest_digest
        || scopeKey(edition.scope) !== scopeKey(request.scope) || scopeKey(request.scope) !== scopeKey(binding.scope)
        || Date.parse(edition.cutoff_at) !== Date.parse(request.cutoff_at) || Date.parse(request.cutoff_at) !== Date.parse(binding.cutoff_at)
        || request.frequency !== binding.columns.frequency) throw new TypeError(`${context} differs from its exact saved fiscal request.`);
    const nodes = new Map(evidence.nodes.map((node) => [node.node_id, node]));
    const observations = new Map(evidence.observations.map((item) => [item.observation_id, item]));
    const sources = new Map(evidence.source_uses.map((source) => [source.source_validation_ref.artifact_id, source]));
    if (nodes.size !== evidence.nodes.length || observations.size !== evidence.observations.length || sources.size !== evidence.source_uses.length
        || [...nodes.keys()].some((id) => observations.has(id))) throw new TypeError(`${context} repeats a graph identity.`);
    for (const source of evidence.source_uses) {
        if (source.source_document.issuer_id !== binding.scope.issuer_id) throw new TypeError(`${context} has a source outside its issuer.`);
        const url = new URL(source.source_document.primary_document_url);
        if (url.protocol !== 'https:') throw new TypeError(`${context} has an invalid source document URL.`);
    }
    for (const observation of evidence.observations) {
        const source = sources.get(observation.source_artifact_id);
        if (!source || observation.source_binding_digest !== source.source_binding_digest || observation.issuer_id !== source.source_document.issuer_id
            || observation.basis.issuer_id !== source.source_document.issuer_id || observation.accession_number !== source.source_document.accession_number
            || observation.source_locator.primary_document_sha256 !== source.source_document.archive_member_sha256) throw new TypeError(`${context} has inconsistent observation source identity.`);
        if (observation.value !== null) decimal(observation.value, `${context}.observation.value`);
    }
    for (const node of evidence.nodes) {
        if ([...node.input_edges, ...node.verification_edges].some((edge) => !nodes.has(edge.input_id) && !observations.has(edge.input_id))
            || node.verification_node_ids.some((id) => !nodes.has(id))
            || [...node.source_observation_ids, ...node.verification_observation_ids].some((id) => !observations.has(id))) throw new TypeError(`${context} has an unresolved graph dependency.`);
        const available = node.availability === 'reported' || node.availability === 'derived';
        if (available !== (node.value !== null) || (node.availability === 'derived' && (!node.formula || node.input_edges.length === 0))) throw new TypeError(`${context} has inconsistent node availability.`);
        if (node.value !== null) decimal(node.value, `${context}.node.value`);
    }
    const visiting = new Set<string>();
    const visited = new Set<string>();
    function visit(id: string) {
        if (visiting.has(id)) throw new TypeError(`${context} has a cyclic input graph.`);
        if (visited.has(id)) return;
        const node = nodes.get(id);
        if (!node) return;
        visiting.add(id);
        for (const edge of [...node.input_edges, ...node.verification_edges]) visit(edge.input_id);
        visiting.delete(id); visited.add(id);
    }
    nodes.forEach((_, id) => visit(id));
    const count = binding.columns.frequency === 'quarter' ? binding.columns.periods.length : binding.columns.windows.length;
    if (new Set(result.rows.map(({ row }) => row.row_id)).size !== result.rows.length) throw new TypeError(`${context} repeats a row.`);
    for (const row of result.rows) {
        if (row.cells.length !== count) throw new TypeError(`${context} has a row outside its selected columns.`);
        for (const cell of row.cells) {
            const node = nodes.get(cell.node_id);
            if (!node || node.row_id !== row.row.row_id || node.statement !== row.row.statement || node.frequency !== request.frequency || node.availability !== cell.kind) throw new TypeError(`${context} has an inconsistent cell graph root.`);
            if (cell.kind === 'reported' || cell.kind === 'derived') {
                if (cell.decimal !== node.value) throw new TypeError(`${context} cell Decimal differs from its graph root.`);
                if (cell.kind === 'reported' && JSON.stringify(cell.source_observation_ids) !== JSON.stringify(node.source_observation_ids)) throw new TypeError(`${context} reported cell source differs.`);
            } else if (cell.reason_code !== node.reason_code) throw new TypeError(`${context} missing cell reason differs.`);
        }
    }
    if ([...evidence.reconciliations, ...evidence.cash_continuities].some((item) => item.input_node_ids.some((id) => !nodes.has(id)))) throw new TypeError(`${context} has an unresolved reconciliation input.`);
    return saved;
}
