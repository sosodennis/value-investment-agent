import { useCallback } from 'react';
import useSWR from 'swr';
import { clientLogger } from '@/lib/logger';
import { buildArtifactReferenceUrl } from '@/features/artifacts/api';
import type { ArtifactReference } from '@/types/agents';
import { parseApiErrorMessage } from '@/types/protocol';
import {
    ArtifactKind,
    parseArtifactEnvelope,
} from '@/types/agents/artifact-envelope-parser';

type ArtifactParser<T> = (value: unknown, context: string) => T;
type ArtifactTarget = string | ArtifactReference | null | undefined;
type ArtifactCacheOptions = {
    dedupingInterval?: number;
};

export type ArtifactRetryContract = {
    retry: () => Promise<unknown>;
    isRetrying: boolean;
    retryable: boolean;
};

export class ArtifactFetchError extends Error {
    readonly status: number;
    readonly retryable: boolean;

    constructor(message: string, status: number) {
        super(message);
        this.name = 'ArtifactFetchError';
        this.status = status;
        this.retryable = status === 0 || status === 408 || status === 425 || status === 429 || status >= 500;
    }
}

const readErrorMessage = async (response: Response): Promise<string> => {
    try {
        const raw: unknown = await response.json();
        return (
            parseApiErrorMessage(raw) ||
            `Failed to fetch artifact (HTTP ${response.status}).`
        );
    } catch {
        return `Failed to fetch artifact (HTTP ${response.status}).`;
    }
};

const fetchArtifact = async <T>(
    url: string,
    parser: ArtifactParser<T>,
    context: string,
    expectedKind?: ArtifactKind
): Promise<T> => {
    clientLogger.debug('artifact.fetch.start', { url, context, expectedKind });
    let response: Response;
    try {
        response = await fetch(url, { credentials: 'include' });
    } catch (error) {
        clientLogger.error('artifact.fetch.network_error', {
            url,
            context,
            error: error instanceof Error ? error.message : String(error),
        });
        throw new ArtifactFetchError(
            error instanceof Error && error.message
                ? error.message
                : 'Network request failed while fetching artifact.',
            0
        );
    }
    try {
        if (!response.ok) {
            clientLogger.error('artifact.fetch.http_error', {
                url,
                status: response.status,
                statusText: response.statusText,
            });
            throw new ArtifactFetchError(
                await readErrorMessage(response),
                response.status
            );
        }
        let data: unknown;
        try {
            data = await response.json();
        } catch (error) {
            if (error instanceof TypeError) {
                clientLogger.error('artifact.fetch.body_network_error', {
                    url,
                    context,
                    error: error.message,
                });
                throw new ArtifactFetchError(
                    error.message || 'Network interrupted while reading artifact data.',
                    0
                );
            }
            throw error;
        }
        const envelope = parseArtifactEnvelope(
            data,
            `${context}.envelope`,
            expectedKind
        );
        const parsed = parser(envelope.data, `${context}.data`);
        clientLogger.debug('artifact.fetch.success', {
            url,
            context,
            kind: envelope.kind,
            version: envelope.version,
        });
        return parsed;
    } catch (err) {
        clientLogger.error('artifact.fetch.error', {
            url,
            context,
            error: err instanceof Error ? err.message : String(err),
        });
        throw err;
    }
};

export function useArtifact<T>(
    target: ArtifactTarget,
    parser: ArtifactParser<T>,
    context: string,
    expectedKind?: ArtifactKind,
    cacheOptions?: ArtifactCacheOptions
) {
    const url = target == null ? null : buildArtifactReferenceUrl(target);
    const fetcher = useCallback(
        (url: string) => fetchArtifact(url, parser, context, expectedKind),
        [parser, context, expectedKind]
    );

    const { data, error, isLoading, isValidating, mutate } = useSWR<T>(
        url ?? null,
        fetcher,
        {
            revalidateOnFocus: false,
            dedupingInterval: cacheOptions?.dedupingInterval ?? 60000, // Cache for 1 minute
            shouldRetryOnError: false,
        }
    );
    const retry = useCallback(
        () => mutate().catch(() => undefined),
        [mutate]
    );
    const retryContract: ArtifactRetryContract = {
        retry,
        isRetrying: isValidating && error !== undefined,
        retryable: error instanceof ArtifactFetchError && error.retryable,
    };

    return {
        data,
        isLoading,
        error,
        ...retryContract,
    };
}
