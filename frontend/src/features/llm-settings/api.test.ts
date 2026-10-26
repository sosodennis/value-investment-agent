import { afterEach, describe, expect, it, vi } from 'vitest';

import { replaceLlmProviderKey } from './api';

describe('replaceLlmProviderKey', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('posts a replacement key to the existing provider-key route and parses the result', async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
            id: 'managed/one',
            label: 'Primary key',
            suffix: '9876',
            fingerprint: 'f00dbabe1234',
            created_at: '2026-10-25T00:00:00Z',
            status: 'healthy',
        }), { status: 201, headers: { 'Content-Type': 'application/json' } }));
        vi.stubGlobal('fetch', fetchMock);

        const key = await replaceLlmProviderKey('managed/one', {
            label: 'Primary key',
            api_key: 'sk-or-v1-replacement-secret',
        });

        expect(fetchMock).toHaveBeenCalledWith(
            'http://localhost:8000/api/v1/llm/provider-keys/managed%2Fone/replace',
            expect.objectContaining({
                method: 'POST',
                credentials: 'include',
                body: JSON.stringify({
                    label: 'Primary key',
                    api_key: 'sk-or-v1-replacement-secret',
                }),
            }),
        );
        expect(key).toMatchObject({ id: 'managed/one', suffix: '9876', status: 'healthy' });
    });
});
