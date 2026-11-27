import { describe, expect, it } from 'vitest';
import { loadStatementReadFixture, statementEnvelope } from '@/test-fixtures/statement-read';
import { parseFundamentalArtifact } from './artifact-parsers';
import { parseStatementCatalog, parseStatementRead } from './statement-read';

describe('statement read runtime boundary', () => {
    it.each(['annual', 'quarter', 'ttm'] as const)('accepts the serialized %s contract before the legacy outer ticker parser', (frequency) => {
        const artifact = parseFundamentalArtifact(statementEnvelope(frequency).data);
        expect(artifact.ticker).toBe(artifact.statement_read?.edition.ticker);
        expect(artifact.company_name).toBe(artifact.statement_read?.edition.company_name);
        expect(artifact.statement_read?.read.kind).toBe(frequency === 'annual' ? 'annual' : 'fiscal');
    });

    it('rejects mismatched release pairs and frequencies rather than rebinding the saved edition', () => {
        const saved = loadStatementReadFixture('quarter');
        saved.edition.fiscal_manifest_digest = '0'.repeat(64);
        expect(() => parseStatementRead(saved)).toThrow(/exact saved fiscal request/);
        const other = loadStatementReadFixture('quarter');
        if (other.read.kind !== 'fiscal') throw new Error('Fiscal fixture required');
        other.read.request.frequency = 'ttm';
        expect(() => parseStatementRead(other)).toThrow(/exact saved fiscal request/);
    });

    it('rejects detached source identity, unresolved inputs and a cell value that differs from its node', () => {
        const source = loadStatementReadFixture('ttm');
        if (source.read.kind !== 'fiscal') throw new Error('Fiscal fixture required');
        source.read.result.evidence.observations[0].source_locator.primary_document_sha256 = '0'.repeat(64);
        expect(() => parseStatementRead(source)).toThrow(/observation source identity/);
        const dependency = loadStatementReadFixture('ttm');
        if (dependency.read.kind !== 'fiscal') throw new Error('Fiscal fixture required');
        dependency.read.result.evidence.nodes.find((node) => node.input_edges.length)?.input_edges.push({ input_id: 'missing-node', coefficient: -1 });
        expect(() => parseStatementRead(dependency)).toThrow(/unresolved graph dependency/);
        const cell = loadStatementReadFixture('ttm');
        if (cell.read.kind !== 'fiscal') throw new Error('Fiscal fixture required');
        const first = cell.read.result.rows[0].cells[0];
        if (first.kind === 'derived') first.decimal = '0';
        expect(() => parseStatementRead(cell)).toThrow(/Decimal differs/);
    });

    it('requires serialized defaults and Decimal strings without mutating the input', () => {
        const saved = loadStatementReadFixture('quarter');
        const original = JSON.stringify(saved);
        parseStatementRead(saved);
        expect(JSON.stringify(saved)).toBe(original);
        const wire: unknown = JSON.parse(original.replace('"input_edges":[]', '"input_edges":null'));
        expect(() => parseStatementRead(wire)).toThrow(/violates the statement contract/);
        expect(() => parseStatementRead(JSON.parse(original.replace('"input_edges":[],', '')))).toThrow(/violates the statement contract/);
        const cellNumber: unknown = JSON.parse(original.replace('"decimal":"117154000000"', '"decimal":117154000000'));
        expect(() => parseStatementRead(cellNumber)).toThrow(/violates the statement contract/);
    });

    it('accepts distinct editions of one issuer and rejects duplicate edition selectors', () => {
        const edition = loadStatementReadFixture('quarter').edition;
        expect(parseStatementCatalog({ contract_version: 'workspace.statement-reader.v2', entries: [edition, { ...edition, edition_id: 'other-cutoff' }] }).entries).toHaveLength(2);
        expect(() => parseStatementCatalog({ contract_version: 'workspace.statement-reader.v2', entries: [edition, edition] })).toThrow(/repeats an edition identity/);
    });
});
