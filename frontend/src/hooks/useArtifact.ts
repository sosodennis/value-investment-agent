import { useCallback } from 'react';
import useSWR from 'swr';
import { parseApiErrorMessage } from '@/types/protocol';

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
    context: string
): Promise<T> => {
    console.log(`[useArtifact] Fetching: ${url}`);
    try {
        const res = await fetch(url);
        if (!res.ok) {
            console.error(`[useArtifact] HTTP Error: ${res.status} ${res.statusText}`);
            throw new Error(await readErrorMessage(res));
        }
        const data: unknown = await res.json();
        const parsed = parser(data, context);
        console.log(`[useArtifact] Success:`, data);
        return parsed;
    } catch (err) {
        console.error(`[useArtifact] Fetch Error:`, err);
        throw err;
    }
};

export function useArtifact<T>(
    artifactId: string | null | undefined,
    parser: ArtifactParser<T>,
    context: string
) {
    const fetcher = useCallback(
        (url: string) => fetchArtifact(url, parser, context),
        [parser, context]
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
