import { afterEach, describe, expect, it, vi } from 'vitest';
import { readAnnualStatementArtifact } from './annual-statements-api';

afterEach(() => { vi.unstubAllGlobals(); document.cookie = 'app_csrf=; max-age=0'; });

describe('annual statement read intent', () => {
    it('creates an owned standalone report with CSRF and preserves its exact reference', async () => {
        document.cookie = 'app_csrf=statement-csrf';
        const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ thread_id: 'new-thread', reference: { artifact_id: 'saved-1', download_url: '/api/v1/artifacts/saved-1?thread_id=new-thread', type: 'financial_reports' } })));
        vi.stubGlobal('fetch', fetch);
        const result = await readAnnualStatementArtifact({ intent: { kind: 'new_thread', creation_id: '56f29c65-fef4-4ccd-a6aa-cae123e9e71d', issuer_id: '0000000001' }, signal: new AbortController().signal });
        expect(result).toEqual({ threadId: 'new-thread', reference: { artifact_id: 'saved-1', download_url: '/api/v1/artifacts/saved-1?thread_id=new-thread', type: 'financial_reports' } });
        expect(fetch).toHaveBeenCalledWith('/api/v1/fundamental/annual-statements/read', expect.objectContaining({ method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'statement-csrf' }, body: JSON.stringify({ kind: 'new_thread', creation_id: '56f29c65-fef4-4ccd-a6aa-cae123e9e71d', issuer_id: '0000000001' }) }));
    });

    it.each([
        { thread_id: 'different', reference: { artifact_id: 'saved-1', download_url: '/api/v1/artifacts/saved-1?thread_id=new-thread', type: 'financial_reports' } },
        { thread_id: 'thread-1', reference: { artifact_id: 'saved-1', download_url: '/api/v1/artifacts/saved-1?run_id=another-run', type: 'financial_reports' } },
    ])('rejects a response outside the requested standalone identity', async (response) => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(response))));
        await expect(readAnnualStatementArtifact({ intent: { kind: 'existing_thread', thread_id: 'thread-1', issuer_id: '0000000001' }, signal: new AbortController().signal })).rejects.toThrow(TypeError);
    });
});
