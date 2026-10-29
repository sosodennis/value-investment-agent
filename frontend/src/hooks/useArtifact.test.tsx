import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { SWRConfig } from 'swr';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ArtifactFetchError, useArtifact } from './useArtifact';

describe('useArtifact', () => {
    const fetchMock = vi.fn();
    const wrapper = ({ children }: { children: ReactNode }) => (
        <SWRConfig value={{ provider: () => new Map() }}>{children}</SWRConfig>
    );

    const artifactResponse = (data: unknown) => new Response(JSON.stringify({
        kind: 'financial_reports',
        version: 'v1',
        produced_by: 'tests',
        created_at: '2026-10-26T00:00:00Z',
        data,
    }), { status: 200 });

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
        renderHook(() => useArtifact(reference, (value) => value, 'test.artifact'), { wrapper });

        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
        expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/artifacts/artifact-1?run_id=run-1');
        expect(fetchMock.mock.calls[0]?.[1]).toEqual({ credentials: 'include' });
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
        ), { wrapper });

        await waitFor(() => expect(result.current.error).toEqual(
            expect.objectContaining({ message: 'artifact data must be an object' }),
        ));
        expect(result.current.data).toBeUndefined();
        expect(result.current.retryable).toBe(false);
    });

    it('retries a transient network failure and returns the completed artifact', async () => {
        fetchMock
            .mockRejectedValueOnce(new TypeError('Network unavailable.'))
            .mockResolvedValueOnce(artifactResponse({ ticker: 'AAPL' }));

        const { result } = renderHook(() => useArtifact(
            'artifact-network-failure',
            (value) => value,
            'test.artifact',
        ), { wrapper });

        await waitFor(() => expect(result.current.error).toEqual(
            expect.objectContaining({
                message: 'Network unavailable.',
                retryable: true,
                status: 0,
            }),
        ));
        expect(result.current.error).toBeInstanceOf(ArtifactFetchError);
        expect(result.current.retryable).toBe(true);
        expect(result.current.data).toBeUndefined();

        await act(async () => {
            await result.current.retry();
        });

        await waitFor(() => expect(result.current.data).toEqual({ ticker: 'AAPL' }));
        expect(result.current.error).toBeUndefined();
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it('allows retry when the response body is interrupted during transfer', async () => {
        const interruptedResponse = new Response();
        vi.spyOn(interruptedResponse, 'json')
            .mockRejectedValueOnce(new TypeError('Response body interrupted.'));
        fetchMock
            .mockResolvedValueOnce(interruptedResponse)
            .mockResolvedValueOnce(artifactResponse({ ticker: 'AAPL' }));

        const { result } = renderHook(() => useArtifact(
            'artifact-body-network-failure',
            (value) => value,
            'test.artifact',
        ), { wrapper });

        await waitFor(() => expect(result.current.retryable).toBe(true));
        expect(result.current.error).toMatchObject({
            message: 'Response body interrupted.',
            status: 0,
        });

        await act(async () => {
            await result.current.retry();
        });

        await waitFor(() => expect(result.current.data).toEqual({ ticker: 'AAPL' }));
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it('retries a 5xx artifact request without refetching a successful sibling', async () => {
        const firstArtifactResponses = [
            new Response(JSON.stringify({ detail: 'Artifact service unavailable.' }), { status: 503 }),
            artifactResponse({ ticker: 'AAPL' }),
        ];
        fetchMock.mockImplementation((input: string) => {
            if (input.includes('artifact-a')) {
                return Promise.resolve(firstArtifactResponses.shift());
            }
            return Promise.resolve(artifactResponse({ ticker: 'MSFT' }));
        });

        const { result } = renderHook(() => ({
            primary: useArtifact('artifact-a', (value) => value, 'test.primary'),
            sibling: useArtifact('artifact-b', (value) => value, 'test.sibling'),
        }), { wrapper });

        await waitFor(() => {
            expect(result.current.primary.retryable).toBe(true);
            expect(result.current.sibling.data).toEqual({ ticker: 'MSFT' });
        });
        expect(result.current.primary.data).toBeUndefined();

        await act(async () => {
            await result.current.primary.retry();
        });

        await waitFor(() => expect(result.current.primary.data).toEqual({ ticker: 'AAPL' }));
        expect(result.current.sibling.data).toEqual({ ticker: 'MSFT' });
        expect(fetchMock).toHaveBeenCalledTimes(3);
        expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('artifact-b'))).toHaveLength(1);
    });

    it('keeps the error visible when a retry also fails', async () => {
        fetchMock
            .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Temporary outage.' }), { status: 503 }))
            .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Still unavailable.' }), { status: 503 }));

        const { result } = renderHook(() => useArtifact(
            'artifact-retry-fails',
            (value) => value,
            'test.artifact',
        ), { wrapper });

        await waitFor(() => expect(result.current.retryable).toBe(true));
        await act(async () => {
            await expect(result.current.retry()).resolves.toBeUndefined();
        });

        await waitFor(() => expect(result.current.error).toMatchObject({
            message: 'Still unavailable.',
            retryable: true,
            status: 503,
        }));
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it.each([401, 404])('does not mark HTTP %s responses as retryable', async (status) => {
        fetchMock.mockResolvedValueOnce(new Response(
            JSON.stringify({ detail: 'Artifact request was rejected.' }),
            { status },
        ));

        const { result } = renderHook(() => useArtifact(
            `artifact-http-${status}`,
            (value) => value,
            'test.artifact',
        ), { wrapper });

        await waitFor(() => expect(result.current.error).toBeInstanceOf(ArtifactFetchError));
        expect(result.current.error).toMatchObject({ status, retryable: false });
        expect(result.current.retryable).toBe(false);
        expect(result.current.data).toBeUndefined();
    });
});
