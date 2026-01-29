import useSWR from 'swr';

const API_URL = process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000';

const fetcher = async (url: string) => {
    const res = await fetch(url);
    if (!res.ok) {
        throw new Error('An error occurred while fetching the artifact.');
    }
    return res.json();
};

export function useArtifact<T>(artifactId?: string | null) {
    const { data, error, isLoading } = useSWR<T>(
        artifactId ? `${API_URL}/artifacts/${artifactId}` : null,
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
