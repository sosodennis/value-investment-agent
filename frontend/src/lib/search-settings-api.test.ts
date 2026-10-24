import { afterEach, describe, expect, it, vi } from 'vitest';
import { getSearchSettings } from './search-settings-api';

describe('Search settings API boundary', () => {
    afterEach(() => vi.unstubAllGlobals());

    it('uses the authenticated product API and parses its response before returning data', async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
            providers: [{ provider: 'ddgs', operations: ['web', 'news'], key_required: false, optional_fields: [] }],
            settings: { providers: [{ provider: 'ddgs', enabled: true, priority: 0, keys: [] }] },
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
        vi.stubGlobal('fetch', fetchMock);

        const result = await getSearchSettings();

        expect(fetchMock).toHaveBeenCalledWith('http://localhost:8000/api/v1/search/settings', expect.objectContaining({ credentials: 'include' }));
        expect(result.settings.providers[0]?.provider).toBe('ddgs');
    });

    it('rejects malformed payloads instead of exposing untyped fields', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ providers: [], settings: { providers: [{ provider: 'ddgs', enabled: 'yes', priority: 0, keys: [] }] } }), { status: 200 })));
        await expect(getSearchSettings()).rejects.toThrow('search_provider_setting.enabled must be a boolean.');
    });

    it('maps service unavailable responses to a typed API error', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'service_unavailable' }), { status: 503 })));
        await expect(getSearchSettings()).rejects.toMatchObject({ status: 503, message: 'service_unavailable' });
    });
});
