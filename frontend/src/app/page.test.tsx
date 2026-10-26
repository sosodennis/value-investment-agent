import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import HomePage from './page';

const router = vi.hoisted(() => ({ push: vi.fn() }));
const api = vi.hoisted(() => ({
    getDashboardCapabilities: vi.fn(),
    getMarketMovers: vi.fn(),
    getRecentAnalyses: vi.fn(),
}));

vi.mock('next/navigation', () => ({ useRouter: () => router }));
vi.mock('@/features/dashboard/api', async (importOriginal) => ({
    ...(await importOriginal<typeof import('@/features/dashboard/api')>()),
    ...api,
}));

const recentPage = {
    source: 'analysis_runtime' as const,
    fetchedAt: '2026-10-25T12:00:00Z',
    nextCursor: null,
    items: [{
        threadId: 'thread/exact-1',
        runId: 'run/exact-1',
        status: 'completed' as const,
        startedAt: '2026-10-25T11:00:00Z',
        updatedAt: '2026-10-25T11:10:00Z',
        ticker: 'AAPL',
        companyName: 'Apple Inc.',
        summary: 'Analysis finished.',
    }],
};

const marketMovers = {
    source: 'yahoo_finance',
    status: 'fresh' as const,
    fetchedAt: '2026-10-25T12:00:00Z',
    items: [{
        symbol: 'NVDA',
        name: 'NVIDIA Corporation',
        price: 140.25,
        changeAbsolute: 2.5,
        changePercent: 1.82,
        currency: 'USD',
        marketState: 'regular',
        quoteTime: '2026-10-25T11:59:00Z',
    }],
    errorCode: null,
};

const capabilities = {
    status: 'degraded' as const,
    checkedAt: '2026-10-25T12:00:00Z',
    capabilities: [{
        id: 'analysis_runtime',
        status: 'operational' as const,
        source: 'readiness_probe',
        checkedAt: '2026-10-25T12:00:00Z',
        detail: null,
    }],
};

describe('home dashboard', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getRecentAnalyses.mockResolvedValue(recentPage);
        api.getMarketMovers.mockResolvedValue(marketMovers);
        api.getDashboardCapabilities.mockResolvedValue(capabilities);
    });

    afterEach(cleanup);

    it('opens the analysis workspace for a company name and shows pending feedback', () => {
        render(<HomePage />);
        const input = screen.getByLabelText('Company name or ticker');
        fireEvent.change(input, { target: { value: '  Apple Inc. ' } });
        fireEvent.submit(input.closest('form')!);

        expect(router.push).toHaveBeenCalledWith('/workspace?ticker=Apple%20Inc.');
        expect(screen.getByRole('button', { name: 'Opening workspace...' }).hasAttribute('disabled')).toBe(true);
    });

    it('shows validation feedback and does not navigate for empty input', () => {
        render(<HomePage />);
        fireEvent.submit(screen.getByLabelText('Company name or ticker').closest('form')!);
        expect(screen.getByRole('alert').textContent).toContain('Enter a company name or ticker');
        expect(router.push).not.toHaveBeenCalled();
    });

    it('renders independent dashboard panels and links each recent analysis to its exact run', async () => {
        render(<HomePage />);

        const analysisLink = await screen.findByRole('link', { name: 'Open analysis run run/exact-1' });
        expect(analysisLink.getAttribute('href')).toBe('/workspace?thread_id=thread%2Fexact-1&run_id=run%2Fexact-1');
        expect(screen.getByText('Apple Inc.')).toBeTruthy();
        expect(screen.getByText('Analysis finished.')).toBeTruthy();
        expect(await screen.findByText('NVIDIA Corporation')).toBeTruthy();
        expect(screen.getByText('Service capabilities')).toBeTruthy();
        expect(screen.getByText('Degraded')).toBeTruthy();
    });

    it('uses neutral labels when persisted company details and summary are absent', async () => {
        api.getRecentAnalyses.mockResolvedValue({
            ...recentPage,
            items: [{ ...recentPage.items[0], ticker: null, companyName: null, summary: null }],
        });
        render(<HomePage />);

        expect(await screen.findByText('Company details unavailable')).toBeTruthy();
        expect(screen.getByText('Summary unavailable.')).toBeTruthy();
        expect(screen.queryByText(/thread\/exact-1/)).toBeNull();
    });

    it('keeps market errors independent and retries only the market panel', async () => {
        api.getMarketMovers.mockRejectedValueOnce(new Error('quotes temporarily unavailable')).mockResolvedValueOnce(marketMovers);
        render(<HomePage />);

        const marketPanel = screen.getByRole('heading', { name: 'Most active' }).closest('section');
        expect(marketPanel).not.toBeNull();
        expect(await within(marketPanel!).findByText('The dashboard data could not be loaded.')).toBeTruthy();
        expect(screen.getByRole('link', { name: 'Open analysis run run/exact-1' })).toBeTruthy();
        fireEvent.click(within(marketPanel!).getByRole('button', { name: 'Retry' }));

        expect(await within(marketPanel!).findByText('NVIDIA Corporation')).toBeTruthy();
        expect(api.getMarketMovers).toHaveBeenCalledTimes(2);
        expect(api.getRecentAnalyses).toHaveBeenCalledTimes(1);
        expect(api.getDashboardCapabilities).toHaveBeenCalledTimes(1);
    });

    it('loads the next page using the server cursor and appends without duplicate runs', async () => {
        api.getRecentAnalyses
            .mockResolvedValueOnce({ ...recentPage, nextCursor: 'opaque-cursor' })
            .mockResolvedValueOnce({ ...recentPage, items: [{ ...recentPage.items[0], threadId: 'thread-2', runId: 'run-2' }] });
        render(<HomePage />);

        fireEvent.click(await screen.findByRole('button', { name: 'Load more analyses' }));
        await waitFor(() => expect(screen.getByRole('link', { name: 'Open analysis run run-2' })).toBeTruthy());
        expect(api.getRecentAnalyses).toHaveBeenNthCalledWith(1, { limit: 10 });
        expect(api.getRecentAnalyses).toHaveBeenNthCalledWith(2, { limit: 10, next_cursor: 'opaque-cursor' });
        expect(screen.getAllByRole('link', { name: /Open analysis run/ })).toHaveLength(2);
    });

    it('shows empty run and capability states independently from stale market data', async () => {
        api.getRecentAnalyses.mockResolvedValue({ ...recentPage, items: [] });
        api.getMarketMovers.mockResolvedValue({
            ...marketMovers,
            status: 'stale',
            errorCode: 'market_data_quote_stale',
        });
        api.getDashboardCapabilities.mockResolvedValue({ ...capabilities, capabilities: [] });
        render(<HomePage />);

        expect(await screen.findByText('No analyses yet')).toBeTruthy();
        expect(await screen.findByText('No capability checks')).toBeTruthy();
        expect(await screen.findByText('Showing the last available market quotes.')).toBeTruthy();
        expect(screen.getByText(/Stale data/)).toBeTruthy();
    });
});
