import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { gunzipSync } from 'node:zlib';
import type { components } from '@/types/generated/api-contract';
import { parseStatementRead } from '@/types/agents/statement-read';
import { loadAnnualStatementFixture } from './annual-statements';

type Frequency = 'annual' | 'quarter' | 'ttm';
function canonical(value: unknown): unknown {
    if (Array.isArray(value)) return value.map(canonical);
    if (value !== null && typeof value === 'object') return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, item]) => [key, canonical(item)]));
    return value;
}

export function loadStatementReadFixture(frequency: Frequency): components['schemas']['StatementReadArtifactV3'] {
    if (frequency === 'annual') {
        const response = loadAnnualStatementFixture();
        return parseStatementRead({
            contract_version: 'workspace.statement-read.v3',
            edition: { edition_id: 'annual-contract-control', label: 'Annual contract control', ticker: 'TEST', company_name: 'Example Issuer', scope: response.statements.scope, cutoff_at: response.statements.cutoff_at, annual_manifest_digest: response.data_release_manifest_digest, fiscal_manifest_digest: 'f'.repeat(64), frequencies: ['annual', 'quarter', 'ttm'] },
            read: { kind: 'annual', response },
        });
    }
    const result: unknown = JSON.parse(gunzipSync(readFileSync(resolve(process.cwd(), `../contracts/fixtures/fiscal-statements-${frequency}.v2.json.gz`))).toString('utf8'));
    if (typeof result !== 'object' || result === null || !('binding' in result) || typeof result.binding !== 'object' || result.binding === null) throw new TypeError('Fiscal fixture lacks its read binding.');
    const binding = result.binding;
    if (!('scope' in binding) || !('cutoff_at' in binding) || !('manifest_digest' in binding)) throw new TypeError('Fiscal fixture lacks its exact selection.');
    return parseStatementRead({
        contract_version: 'workspace.statement-read.v3',
        edition: { edition_id: 'apple-fiscal-contract-control', label: 'Retained Apple contract control', ticker: 'AAPL', company_name: 'Apple Inc.', scope: binding.scope, cutoff_at: binding.cutoff_at, annual_manifest_digest: 'a'.repeat(64), fiscal_manifest_digest: binding.manifest_digest, frequencies: ['annual', 'quarter', 'ttm'] },
        read: { kind: 'fiscal', request: { contract_version: 'fundamental.fiscal-statements.v2', manifest_digest: binding.manifest_digest, scope: binding.scope, cutoff_at: binding.cutoff_at, frequency }, result, result_digest: createHash('sha256').update(JSON.stringify(canonical(result))).digest('hex') },
    });
}

export function statementEnvelope(frequency: Frequency) {
    return { kind: 'financial_reports', version: 'v1', produced_by: 'fundamental_analysis', created_at: '2024-12-01T00:00:00Z', data: { status: 'done', ticker: null, company_name: null, model_type: 'statement_read', financial_reports: [], statement_read: loadStatementReadFixture(frequency) } };
}

export function statementReadResponse(frequency: Frequency, artifactId: string, threadId = 'thread-1') {
    return { contract_version: 'workspace.statement-reader.v2', frequency, edition_id: loadStatementReadFixture(frequency).edition.edition_id, thread_id: threadId, reference: { artifact_id: artifactId, download_url: `/api/v1/artifacts/${artifactId}?thread_id=${threadId}`, type: 'financial_reports' } };
}
