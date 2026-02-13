import { useCallback } from 'react';
import useSWR from 'swr';
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
    console.log(`[useArtifact] Fetching: ${url}`);
    try {
        const res = await fetch(url);
        if (!res.ok) {
            console.error(`[useArtifact] HTTP Error: ${res.status} ${res.statusText}`);
            throw new Error(await readErrorMessage(res));
        }
        const data: unknown = await res.json();
        const envelope = parseArtifactEnvelope(
            data,
            `${context}.envelope`,
            expectedKind
        );
        const parsed = parser(envelope.data, `${context}.data`);
        console.log(`[useArtifact] Success:`, envelope);
        return parsed;
    } catch (err) {
        console.error(`[useArtifact] Fetch Error:`, err);
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
