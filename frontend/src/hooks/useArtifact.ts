import useSWR from 'swr';

const API_URL = process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000';

const fetcher = async (url: string) => {
    console.log(`[useArtifact] Fetching: ${url}`);
    try {
        const res = await fetch(url);
        if (!res.ok) {
            console.error(`[useArtifact] HTTP Error: ${res.status} ${res.statusText}`);
            throw new Error('An error occurred while fetching the artifact.');
        }
        const data = await res.json();
        console.log(`[useArtifact] Success:`, data);
        return data;
    } catch (err) {
        console.error(`[useArtifact] Fetch Error:`, err);
        throw err;
    }
};

export function useArtifact<T>(artifactId?: string | null) {
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
