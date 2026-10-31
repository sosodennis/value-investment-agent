import { afterEach, describe, expect, it, vi } from 'vitest';

import {
    createLlmProviderKeyImport,
    previewLlmProviderKeyImport,
    replaceLlmProviderKey,
} from './api';

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
            '/api/v1/llm/provider-keys/managed%2Fone/replace',
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

describe('provider key import API', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('uploads previews as multipart form data without a JSON content type', async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
            file_type: 'txt',
            row_count: 1,
            unique_count: 1,
            duplicate_count: 0,
            issues: [],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
        vi.stubGlobal('fetch', fetchMock);
        const file = new File(['sk-or-v1-fake-key-value-00000001'], 'keys.txt');

        const preview = await previewLlmProviderKeyImport(file);

        const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
        expect(fetchMock).toHaveBeenCalledWith(
            '/api/v1/llm/provider-keys/imports/preview',
            expect.objectContaining({ method: 'POST', credentials: 'include' }),
        );
        expect(init.body).toBeInstanceOf(FormData);
        expect((init.body as FormData).get('file')).toBe(file);
        expect(new Headers(init.headers).has('Content-Type')).toBe(false);
        expect(preview).toMatchObject({ file_type: 'txt', unique_count: 1 });
    });

    it('sends the idempotency key with the file submission', async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
            id: 'batch-1',
            status: 'queued',
            total_count: 1,
            processed_count: 0,
            imported_count: 0,
            duplicate_count: 0,
            invalid_count: 0,
            retryable_count: 0,
            created_at: '2026-10-31T00:00:00Z',
            updated_at: '2026-10-31T00:00:00Z',
            items: [],
        }), { status: 202, headers: { 'Content-Type': 'application/json' } }));
        vi.stubGlobal('fetch', fetchMock);
        const file = new File(['sk-or-v1-fake-key-value-00000001'], 'keys.txt');

        const batch = await createLlmProviderKeyImport(file, 'client-idempotency-0001');

        expect(fetchMock).toHaveBeenCalledWith(
            '/api/v1/llm/provider-keys/imports',
            expect.objectContaining({
                headers: expect.objectContaining({ 'Idempotency-Key': 'client-idempotency-0001' }),
                body: expect.any(FormData),
            }),
        );
        expect(batch).toMatchObject({ id: 'batch-1', status: 'queued', total_count: 1 });
    });
});
