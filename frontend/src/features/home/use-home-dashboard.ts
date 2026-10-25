import useSWR from 'swr';
import { getCapabilities, getMarketMovers, getRecentAnalyses, HomeApiError } from './home-api';

function useResource<T>(key: string, fetcher: () => Promise<T>) {
    const { data, error, isLoading, isValidating, mutate } = useSWR<T>(key, fetcher, {
        revalidateOnFocus: false,
        shouldRetryOnError: (cause: unknown) =>
            cause instanceof HomeApiError && cause.recoverable,
        errorRetryCount: 2,
        errorRetryInterval: 1000,
    });
    return {
        data,
        error: error instanceof HomeApiError ? error : undefined,
        isLoading,
        isValidating,
        retry: () => mutate(),
    };
}

export const useRecentAnalyses = () => useResource('home:recent-analyses', getRecentAnalyses);
export const useMarketMovers = () => useResource('home:market-movers', getMarketMovers);
export const useCapabilities = () => useResource('home:capabilities', getCapabilities);
