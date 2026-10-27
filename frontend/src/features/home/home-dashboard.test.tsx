import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { HomeApiError } from './home-api';
import { HomeDashboard } from './home-dashboard';

const resources = vi.hoisted(() => ({ recent: {}, market: {}, capabilities: {} } as Record<string, Record<string, unknown>>));

vi.mock('./use-home-dashboard', () => ({
    useRecentAnalyses: () => resources.recent,
    useMarketMovers: () => resources.market,
    useCapabilities: () => resources.capabilities,
}));

const resource = (overrides: Record<string, unknown> = {}) => ({
    data: undefined,
    error: undefined,
    isLoading: false,
    isValidating: false,
    retry: vi.fn().mockResolvedValue(undefined),
    ...overrides,
});

describe('HomeDashboard', () => {
    afterEach(() => { cleanup(); vi.clearAllMocks(); });

    it('renders each resource independently and links the exact recent run', () => {
        Object.assign(resources, {
            recent: resource({ data: { items: [{
                thread_id: 'thread 1', run_id: 'run/2', status: 'completed',
                started_at: '2026-10-24T10:00:00Z', updated_at: '2026-10-24T10:05:00Z',
                ticker: 'AAPL', company_name: 'Apple Inc.',
            }] } }),
            market: resource({ error: new HomeApiError('Market feed failed.', 503, true) }),
            capabilities: resource({ data: { checked_at: '2026-10-24T10:00:00Z', items: [{
                id: 'sec', label: 'SEC EDGAR', status: 'degraded', source: 'health check', checked_at: '2026-10-24T10:00:00Z',
            }] } }),
        });

        render(<HomeDashboard />);

        expect(screen.getByRole('link', { name: /Open Apple Inc\. analysis run run\/2/ }).getAttribute('href'))
            .toBe('/workspace?thread_id=thread+1&run_id=run%2F2');
        screen.getByText('market data unavailable');
        screen.getByText('SEC EDGAR');
        expect(screen.getByText(/health check/).textContent).toContain('checked Oct 24, 2026, 6:00 PM');
    });

    it('shows independent loading, stale source freshness, and retries the failed resource', () => {
        const retry = vi.fn().mockResolvedValue(undefined);
        Object.assign(resources, {
            recent: resource({ isLoading: true }),
            market: resource({ data: {
                source: 'Quote feed', as_of: '2026-10-24T10:00:00Z', fetched_at: '2026-10-24T10:02:00Z',
                status: 'stale', items: [],
            } }),
            capabilities: resource({ error: new HomeApiError('Capability service unavailable.', 503, true), retry }),
        });

        render(<HomeDashboard />);

        screen.getByLabelText('Loading Recent analyses');
        screen.getByText(/Quote feed · stale · as of/);
        screen.getByText(/Fetched/);
        screen.getByText('Showing the last available quotes; source data may be delayed.');
        fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
        expect(retry).toHaveBeenCalledOnce();
    });

    it('offers sign-in for authorization failures without replacing healthy panels', () => {
        Object.assign(resources, {
            recent: resource({ error: new HomeApiError('Forbidden.', 403) }),
            market: resource({ data: { source: 'Quote feed', as_of: 'now', fetched_at: 'now', status: 'unavailable', items: [], error_code: 'provider_down' } }),
            capabilities: resource({ data: { checked_at: 'now', items: [] } }),
        });

        render(<HomeDashboard />);

        screen.getByText('Sign-in required');
        expect(screen.getByRole('link', { name: 'Sign in' }).getAttribute('href')).toBe('/login?next=%2F');
        screen.getByText('Market quotes are currently unavailable (provider_down).');
        screen.getByText('No capability checks available');
    });
});
