import type { components } from '@/types/generated/api-contract';
import type { ArtifactReference } from '@/types/agents';
import { csrfHeaders } from '@/lib/auth-api';
import { parseApiErrorMessage } from '@/types/protocol';
import { array, boolean, nonEmpty, object, timestamp, record } from '@/types/agents/fundamental-parser-primitives';

type Contracts = components['schemas'];
export type AnnualStatementReadIntent = Contracts['AnnualStatementExistingThreadReadIntent'] | Contracts['AnnualStatementNewThreadReadIntent'];
export type AnnualStatementCatalogEntry = Contracts['AnnualStatementCatalogEntry'];
const parseEntry = object<AnnualStatementCatalogEntry>({ issuer_id: nonEmpty, ticker: nonEmpty, company_name: nonEmpty, cutoff_at: timestamp });
const parseCatalog = object<Contracts['AnnualStatementCatalogResponse']>({ entries: array(parseEntry) });
const parseReference = object<Contracts['ArtifactReference']>({ artifact_id: nonEmpty, download_url: nonEmpty, type: nonEmpty });
const parseFailure = object<Contracts['AnnualStatementReadFailure']>({ code: nonEmpty, message: nonEmpty, retryable: boolean });
const parseRead = object<Contracts['AnnualStatementArtifactResponse']>({ reference: parseReference, thread_id: nonEmpty });

async function responseBody(response: Response): Promise<unknown> {
    const value: unknown = await response.json();
    if (!response.ok) {
        const detail = record(value, 'annual statement error').detail;
        if (typeof detail === 'object' && detail !== null && !Array.isArray(detail)) {
            const failure = parseFailure(detail, 'annual statement error.detail');
            throw new Error(`${failure.code} · ${failure.message}`);
        }
        throw new Error(parseApiErrorMessage(value) || `Annual statements unavailable (HTTP ${response.status}).`);
    }
    return value;
}

export async function loadAnnualStatementCatalog(): Promise<AnnualStatementCatalogEntry[]> {
    const response = await fetch('/api/v1/fundamental/annual-statements/catalog', { credentials: 'include' });
    return parseCatalog(await responseBody(response), 'annual statement catalog').entries;
}

export async function readAnnualStatementArtifact({ intent, signal }: {
    intent: AnnualStatementReadIntent; signal: AbortSignal;
}): Promise<{ threadId: string; reference: ArtifactReference }> {
    const response = await fetch('/api/v1/fundamental/annual-statements/read', {
        method: 'POST', credentials: 'include', signal,
        headers: { 'Content-Type': 'application/json', ...csrfHeaders() },
        body: JSON.stringify(intent),
    });
    const result = parseRead(await responseBody(response), 'annual statement read');
    const expectedUrl = `/api/v1/artifacts/${encodeURIComponent(result.reference.artifact_id)}?thread_id=${encodeURIComponent(result.thread_id)}`;
    if (result.reference.type !== 'financial_reports' || result.reference.download_url !== expectedUrl) throw new TypeError('Annual statement read returned an invalid standalone artifact reference.');
    if (intent.kind === 'existing_thread' && result.thread_id !== intent.thread_id) throw new TypeError('Annual statement read returned a different thread.');
    return { threadId: result.thread_id, reference: result.reference };
}
