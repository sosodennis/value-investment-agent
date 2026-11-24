import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SWRConfig } from 'swr';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadAnnualStatementFixture } from '@/test-fixtures/annual-statements';
import { AnnualStatementsReader } from './annual-statements-reader';

beforeEach(() => {
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
    HTMLElement.prototype.scrollIntoView = vi.fn();
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState({}, '', '/workspace'); });

function savedEnvelope() {
    return { kind: 'financial_reports', version: 'v1', produced_by: 'fundamental_analysis', created_at: '2024-12-01T00:00:00Z', data: { status: 'done', ticker: 'TEST', company_name: 'Example Issuer', model_type: 'annual_statements', financial_reports: [], annual_statements: loadAnnualStatementFixture() } };
}
function reader(threadId: string | null = 'thread-1') {
    return <SWRConfig value={{ provider: () => new Map(), shouldRetryOnError: false }}><AnnualStatementsReader threadId={threadId} onEvidenceItems={vi.fn()} /></SWRConfig>;
}

describe('saved annual statement reader', () => {
    it('reloads an exact saved artifact without asking for the current release or a run', async () => {
        window.history.replaceState({}, '', '/workspace?statement_thread=thread-1&statement_artifact=saved-1');
        const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(savedEnvelope()))));
        vi.stubGlobal('fetch', fetch);
        render(reader());
        await screen.findByRole('article', { name: 'Annual financial statements' });
        expect(fetch).toHaveBeenCalledTimes(1);
        expect(fetch).toHaveBeenCalledWith('/api/v1/artifacts/saved-1?thread_id=thread-1', expect.objectContaining({ credentials: 'include' }));
        expect(screen.getByText('Example Issuer · TEST')).toBeTruthy();
    });

    it('keeps a saved statement visible when an explicit fresh read fails', async () => {
        window.history.replaceState({}, '', '/workspace?statement_thread=thread-1&statement_artifact=saved-1');
        const fetch = vi.fn().mockImplementation((url: string) => {
            if (url.includes('/artifacts/')) return Promise.resolve(new Response(JSON.stringify(savedEnvelope())));
            if (url.endsWith('/catalog')) return Promise.resolve(new Response(JSON.stringify({ entries: [{ issuer_id: '0000000001', company_name: 'Example Issuer', ticker: 'TEST', cutoff_at: '2024-12-01T00:00:00Z' }] })));
            return Promise.resolve(new Response(JSON.stringify({ detail: { code: 'STATEMENT_RELEASE_UNAVAILABLE', message: 'Prepared release unavailable.', retryable: true } }), { status: 503 }));
        });
        vi.stubGlobal('fetch', fetch);
        render(reader());
        await screen.findByRole('article', { name: 'Annual financial statements' });
        fireEvent.click(screen.getByRole('combobox', { name: 'Statement company' }));
        fireEvent.click(await screen.findByRole('option', { name: /Example Issuer/ }));
        fireEvent.click(screen.getByRole('button', { name: 'Read prepared statements' }));
        await screen.findByText(/Prepared release unavailable/);
        expect(screen.getByRole('article', { name: 'Annual financial statements' })).toBeTruthy();
        expect(window.location.search).toContain('statement_artifact=saved-1');
    });

    it('retains the new-read creation identity across an upstream failure and retry', async () => {
        const intents: string[] = [];
        const fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
            if (url.includes('/artifacts/')) return Promise.resolve(new Response(JSON.stringify(savedEnvelope())));
            if (url.endsWith('/catalog')) return Promise.resolve(new Response(JSON.stringify({ entries: [{ issuer_id: '0000000001', company_name: 'Example Issuer', ticker: 'TEST', cutoff_at: '2024-12-01T00:00:00Z' }] })));
            intents.push(String(init?.body));
            return Promise.resolve(intents.length === 1
                ? new Response(JSON.stringify({ detail: { code: 'UPSTREAM_UNAVAILABLE', message: 'Read unavailable.', retryable: true } }), { status: 502 })
                : new Response(JSON.stringify({ thread_id: 'new-thread', reference: { artifact_id: 'saved-1', download_url: '/api/v1/artifacts/saved-1?thread_id=new-thread', type: 'financial_reports' } })));
        });
        vi.stubGlobal('fetch', fetch);
        render(reader(null));
        fireEvent.click(screen.getByRole('combobox', { name: 'Statement company' }));
        fireEvent.click(await screen.findByRole('option', { name: /Example Issuer/ }));
        fireEvent.click(screen.getByRole('button', { name: 'Read prepared statements' }));
        await screen.findByText(/UPSTREAM_UNAVAILABLE/);
        expect(new URLSearchParams(window.location.search).get('statement_creation')).toMatch(/^[0-9a-f-]{36}$/);
        fireEvent.click(screen.getByRole('button', { name: 'Read prepared statements' }));
        await screen.findByRole('article', { name: 'Annual financial statements' });
        expect(intents).toHaveLength(2);
        expect(intents[1]).toBe(intents[0]);
        expect(window.location.search).toContain('statement_thread=new-thread');
    });

    it('does not load a statement link belonging to another thread', async () => {
        window.history.replaceState({}, '', '/workspace?statement_thread=other-thread&statement_artifact=saved-1');
        const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
        render(reader('current-thread'));
        await act(async () => { await Promise.resolve(); });
        await waitFor(() => expect(fetch).not.toHaveBeenCalled());
        expect(screen.queryByRole('article', { name: 'Annual financial statements' })).toBeNull();
    });
});
