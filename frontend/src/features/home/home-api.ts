import { parseApiErrorMessage } from '@/types/protocol';
import { parseCapabilities, parseMarketMovers, parseRecentAnalyses } from './home-parsers';

export class HomeApiError extends Error {
    constructor(message: string, readonly status?: number, readonly recoverable = false) {
        super(message);
        this.name = 'HomeApiError';
    }
}

async function readError(response: Response, resource: string): Promise<HomeApiError> {
    let message = `${resource} request failed (HTTP ${response.status}).`;
    try {
        const payload: unknown = await response.json();
        message = parseApiErrorMessage(payload) || message;
    } catch { /* The HTTP status remains useful without an error body. */ }
    return new HomeApiError(message, response.status, response.status >= 500);
}

async function getResource<T>(path: string, label: string, parse: (value: unknown) => T): Promise<T> {
    let response: Response;
    try {
        response = await fetch(path, {
            credentials: 'include',
            headers: { Accept: 'application/json' },
        });
    } catch (error) {
        throw new HomeApiError(
            error instanceof Error ? error.message : `${label} request failed.`,
            undefined,
            true
        );
    }
    if (!response.ok) throw await readError(response, label);
    let payload: unknown;
    try {
        payload = await response.json();
    } catch {
        throw new HomeApiError(`${label} response is not valid JSON.`);
    }
    try {
        return parse(payload);
    } catch (error) {
        throw new HomeApiError(error instanceof Error ? error.message : `${label} response is malformed.`);
    }
}

export const getRecentAnalyses = () =>
    getResource('/api/v1/dashboard/recent-analyses', 'Recent analyses', parseRecentAnalyses);

export const getMarketMovers = () =>
    getResource('/api/v1/dashboard/market-movers', 'Market movers', parseMarketMovers);

export const getCapabilities = () =>
    getResource('/api/v1/dashboard/capabilities', 'Capabilities', parseCapabilities);
