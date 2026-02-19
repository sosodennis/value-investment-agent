import { useCallback } from 'react';
import useSWR from 'swr';
import { clientLogger } from '@/lib/logger';
import { parseApiErrorMessage } from '@/types/protocol';
import {
    ArtifactKind,
    parseArtifactEnvelope,
} from '@/types/agents/artifact-envelope-parser';

const API_URL = process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000';

type ArtifactParser<T> = (value: unknown, context: string) => T;

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
    try {
        const res = await fetch(url);
        if (!res.ok) {
            clientLogger.error('artifact.fetch.http_error', {
                url,
                status: res.status,
                statusText: res.statusText,
            });
            throw new Error(await readErrorMessage(res));
        }
        const data: unknown = await res.json();
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
    artifactId: string | null | undefined,
    parser: ArtifactParser<T>,
    context: string,
    expectedKind?: ArtifactKind
) {
    const fetcher = useCallback(
        (url: string) => fetchArtifact(url, parser, context, expectedKind),
        [parser, context, expectedKind]
    );

    const { data, error, isLoading } = useSWR<T>(
        artifactId ? `${API_URL}/api/artifacts/${artifactId}` : null,
        fetcher,
        {
            revalidateOnFocus: false,
            dedupingInterval: 60000, // Cache for 1 minute
            shouldRetryOnError: false,
        }
    );

    return {
        data,
        isLoading,
        error,
    };
}
