import { afterEach, describe, expect, it, vi } from 'vitest';
import { statementReadResponse } from '@/test-fixtures/statement-read';
import { readStatementArtifact } from './statement-reader-api';

afterEach(() => { vi.unstubAllGlobals(); document.cookie = 'app_csrf=; max-age=0'; });

describe('statement read intent', () => {
    it('creates an owned standalone edition with CSRF and exact frequency', async () => {
        document.cookie = 'app_csrf=statement-csrf';
        const response = statementReadResponse('annual', 'saved-1', 'new-thread');
        const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(response)));
        vi.stubGlobal('fetch', fetch);
        const intent = { contract_version: 'workspace.statement-reader.v2', kind: 'new_thread', creation_id: '56f29c65-fef4-4ccd-a6aa-cae123e9e71d', edition_id: response.edition_id, frequency: 'annual' } as const;
        const result = await readStatementArtifact({ intent, signal: new AbortController().signal });
        expect(result).toEqual({ threadId: 'new-thread', reference: response.reference, editionId: response.edition_id });
        expect(fetch).toHaveBeenCalledWith('/api/v1/fundamental/statements/read', expect.objectContaining({ method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'statement-csrf' }, body: JSON.stringify(intent) }));
    });

    it('sends only the authorized saved identity for frequency changes', async () => {
        const response = statementReadResponse('ttm', 'ttm-saved');
        const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(response)));
        vi.stubGlobal('fetch', fetch);
        const intent = { contract_version: 'workspace.statement-reader.v2', kind: 'saved_artifact', thread_id: 'thread-1', artifact_id: 'quarter-saved', frequency: 'ttm' } as const;
        await readStatementArtifact({ intent, signal: new AbortController().signal });
        expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual(intent);
    });

    it.each([
        { thread_id: 'different' }, { frequency: 'quarter' }, { edition_id: 'different-edition' },
        { reference: { artifact_id: 'saved-1', download_url: '/api/v1/artifacts/saved-1?run_id=another-run', type: 'financial_reports' } },
    ])('rejects a response outside the requested standalone selection', async (delta) => {
        const response = { ...statementReadResponse('annual', 'saved-1'), ...delta };
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(response))));
        await expect(readStatementArtifact({ intent: { contract_version: 'workspace.statement-reader.v2', kind: 'existing_thread', thread_id: 'thread-1', edition_id: 'annual-contract-control', frequency: 'annual' }, signal: new AbortController().signal })).rejects.toThrow(TypeError);
    });
});
