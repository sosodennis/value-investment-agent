import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useArtifact } from './useArtifact';

describe('useArtifact', () => {
    const fetchMock = vi.fn();

    beforeEach(() => {
        vi.stubGlobal('fetch', fetchMock);
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        fetchMock.mockReset();
    });

    it('uses a completed output reference URL including its run scope', async () => {
        fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
            kind: 'financial_reports',
            version: 'v1',
            produced_by: 'tests',
            created_at: '2026-10-26T00:00:00Z',
            data: { ticker: 'AAPL' },
        }), { status: 200 }));

        const reference = {
            artifact_id: 'artifact-1',
            download_url: 'http://localhost:8000/api/v1/artifacts/artifact-1?run_id=run-1',
            type: 'financial_reports',
        };
        renderHook(() => useArtifact(reference, (value) => value, 'test.artifact'));

        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
        expect(fetchMock.mock.calls[0]?.[0]).toBe(reference.download_url);
    });

    it('surfaces malformed artifact payloads as errors', async () => {
        fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
            kind: 'financial_reports',
            version: 'v1',
            produced_by: 'tests',
            created_at: '2026-10-26T00:00:00Z',
            data: null,
        }), { status: 200 }));

        const { result } = renderHook(() => useArtifact(
            'artifact-1',
            (value) => {
                if (typeof value !== 'object' || value === null) {
                    throw new TypeError('artifact data must be an object');
                }
                return value;
            },
            'test.artifact',
            'financial_reports',
        ));

        await waitFor(() => expect(result.current.error).toEqual(
            expect.objectContaining({ message: 'artifact data must be an object' }),
        ));
        expect(result.current.data).toBeUndefined();
    });

    it('surfaces network failures without producing artifact data', async () => {
        fetchMock.mockRejectedValueOnce(new TypeError('Network unavailable.'));

        const { result } = renderHook(() => useArtifact(
            'artifact-network-failure',
            (value) => value,
            'test.artifact',
        ));

        await waitFor(() => expect(result.current.error).toEqual(
            expect.objectContaining({ message: 'Network unavailable.' }),
        ));
        expect(result.current.data).toBeUndefined();
    });
});
