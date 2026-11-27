import type { components } from '@/types/generated/api-contract';
import type { ArtifactReference } from '@/types/agents';
import { csrfHeaders } from '@/lib/auth-api';
import { parseApiErrorMessage } from '@/types/protocol';
import { boolean, nonEmpty, object, record, literal } from '@/types/agents/fundamental-parser-primitives';
import { parseStatementCatalog } from '@/types/agents/statement-read';

type Contracts = components['schemas'];
export type StatementReadIntent = Contracts['StatementExistingThreadIntentV2'] | Contracts['StatementNewThreadIntentV2'] | Contracts['StatementSavedArtifactIntentV2'];
export type StatementEdition = Contracts['StatementEditionV2'];
export type StatementFrequency = StatementReadIntent['frequency'];
const parseReference = object<Contracts['ArtifactReference']>({ artifact_id: nonEmpty, download_url: nonEmpty, type: nonEmpty });
const parseFailure = object<Contracts['AnnualStatementReadFailure']>({ code: nonEmpty, message: nonEmpty, retryable: boolean });
const parseRead = object<Contracts['StatementArtifactResponseV2']>({
    contract_version: literal('workspace.statement-reader.v2'), edition_id: nonEmpty,
    frequency: literal('annual', 'quarter', 'ttm'), reference: parseReference, thread_id: nonEmpty,
});

async function responseBody(response: Response): Promise<unknown> {
    const value: unknown = await response.json();
    if (!response.ok) {
        const detail = record(value, 'statement error').detail;
        if (typeof detail === 'object' && detail !== null && !Array.isArray(detail)) {
            const failure = parseFailure(detail, 'statement error.detail');
            throw new Error(`${failure.code} · ${failure.message}`);
        }
        throw new Error(parseApiErrorMessage(value) || `Statements unavailable (HTTP ${response.status}).`);
    }
    return value;
}

export async function loadStatementCatalog(): Promise<StatementEdition[]> {
    const response = await fetch('/api/v1/fundamental/statements/catalog', { credentials: 'include', cache: 'no-store' });
    return parseStatementCatalog(await responseBody(response), 'statement catalog').entries;
}

export async function readStatementArtifact({ intent, signal }: {
    intent: StatementReadIntent; signal: AbortSignal;
}): Promise<{ threadId: string; reference: ArtifactReference; editionId: string }> {
    const response = await fetch('/api/v1/fundamental/statements/read', {
        method: 'POST', credentials: 'include', signal,
        headers: { 'Content-Type': 'application/json', ...csrfHeaders() },
        body: JSON.stringify(intent),
    });
    const result = parseRead(await responseBody(response), 'statement read');
    const expectedUrl = `/api/v1/artifacts/${encodeURIComponent(result.reference.artifact_id)}?thread_id=${encodeURIComponent(result.thread_id)}`;
    if (result.reference.type !== 'financial_reports' || result.reference.download_url !== expectedUrl) throw new TypeError('Statement read returned an invalid standalone artifact reference.');
    if (intent.kind !== 'new_thread' && result.thread_id !== intent.thread_id) throw new TypeError('Statement read returned a different thread.');
    if (result.frequency !== intent.frequency || (intent.kind !== 'saved_artifact' && result.edition_id !== intent.edition_id)) throw new TypeError('Statement read returned a different edition or frequency.');
    return { threadId: result.thread_id, reference: result.reference, editionId: result.edition_id };
}
