import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SWRConfig } from 'swr';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadAnnualStatementFixture } from '@/test-fixtures/annual-statements';
import { loadStatementReadFixture, statementEnvelope, statementReadResponse } from '@/test-fixtures/statement-read';
import { StatementReader } from './statement-reader';

beforeEach(() => {
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
    HTMLElement.prototype.scrollIntoView = vi.fn();
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState({}, '', '/workspace'); });
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
function reader(threadId: string | null = 'thread-1') {
    return <SWRConfig value={{ provider: () => new Map(), shouldRetryOnError: false }}><StatementReader threadId={threadId} onEvidenceItems={vi.fn()} /></SWRConfig>;
}
function openSaved(frequency: 'annual' | 'quarter' | 'ttm', id = 'saved-1') {
    window.history.replaceState({}, '', `/workspace?statement_thread=thread-1&statement_artifact=${id}&statement_frequency=${frequency}`);
}
function catalog(frequency: 'annual' | 'quarter' | 'ttm' = 'annual') {
    return { contract_version: 'workspace.statement-reader.v2', entries: [loadStatementReadFixture(frequency).edition] };
}

describe('saved statement reader', () => {
    it('reloads an exact fiscal artifact with a fresh current-access GET and no catalog or workflow request', async () => {
        openSaved('quarter');
        const fetch = vi.fn().mockResolvedValue(json(statementEnvelope('quarter'))); vi.stubGlobal('fetch', fetch);
        const view = render(reader());
        await screen.findByRole('article', { name: 'Quarterly financial statements' });
        expect(fetch).toHaveBeenCalledTimes(1);
        expect(fetch).toHaveBeenCalledWith('/api/v1/artifacts/saved-1?thread_id=thread-1', expect.objectContaining({ credentials: 'include', cache: 'no-store', signal: expect.any(AbortSignal) }));
        view.unmount();
        fetch.mockResolvedValue(json({ detail: 'Current release permission refused.' }, 403));
        render(reader());
        await screen.findByText('Current release permission refused.');
        expect(screen.queryByRole('article')).toBeNull();
        expect(fetch).toHaveBeenCalledTimes(2);
    });

    it('keeps legacy annual saved values and missing FX semantics', async () => {
        window.history.replaceState({}, '', '/workspace?statement_thread=thread-1&statement_artifact=saved-1');
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ kind: 'financial_reports', version: 'v1', produced_by: 'fundamental_analysis', created_at: '2024-12-01T00:00:00Z', data: { status: 'done', ticker: 'TEST', company_name: 'Example Issuer', model_type: 'annual_statements', financial_reports: [], annual_statements: loadAnnualStatementFixture() } })));
        render(reader());
        await screen.findByRole('article', { name: 'Annual financial statements' });
        expect(screen.getByText('Example Issuer · TEST')).toBeTruthy();
        expect(screen.getByRole('radio', { name: 'Quarterly' })).toHaveProperty('disabled', true);
    });

    it('changes a saved frequency using its artifact, without depending on a catalog entry', async () => {
        openSaved('quarter');
        const calls: unknown[] = [];
        vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string, init?: RequestInit) => {
            if (url.endsWith('/read')) { calls.push(JSON.parse(String(init?.body))); return Promise.resolve(json(statementReadResponse('ttm', 'saved-ttm'))); }
            return Promise.resolve(json(statementEnvelope(url.includes('saved-ttm') ? 'ttm' : 'quarter')));
        }));
        render(reader());
        await screen.findByRole('article', { name: 'Quarterly financial statements' });
        fireEvent.click(screen.getByRole('radio', { name: 'TTM' }));
        expect(screen.queryByRole('article')).toBeNull();
        await screen.findByRole('article', { name: 'TTM financial statements' });
        expect(calls).toEqual([{ contract_version: 'workspace.statement-reader.v2', kind: 'saved_artifact', thread_id: 'thread-1', artifact_id: 'saved-1', frequency: 'ttm' }]);
        expect(window.location.search).toContain('statement_artifact=saved-ttm');
        expect(window.location.search).toContain('statement_frequency=ttm');
    });

    it('aborts rapid frequency changes and ignores a late response even when the transport resolves it', async () => {
        openSaved('quarter');
        let late: (response: Response) => void = () => undefined;
        let firstSignal: AbortSignal | undefined;
        let reads = 0;
        vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string, init?: RequestInit) => {
            if (url.endsWith('/read')) {
                reads++;
                if (reads === 1) { firstSignal = init?.signal ?? undefined; return new Promise<Response>((resolve) => { late = resolve; }); }
                return Promise.resolve(json(statementReadResponse('quarter', 'new-quarter')));
            }
            return Promise.resolve(json(statementEnvelope('quarter')));
        }));
        render(reader());
        await screen.findByRole('article', { name: 'Quarterly financial statements' });
        fireEvent.click(screen.getByRole('radio', { name: 'TTM' }));
        fireEvent.click(screen.getByRole('radio', { name: 'Quarterly' }));
        await screen.findByRole('article', { name: 'Quarterly financial statements' });
        expect(firstSignal?.aborted).toBe(true);
        await act(async () => late(json(statementReadResponse('ttm', 'late-ttm'))));
        expect(window.location.search).toContain('statement_artifact=new-quarter');
        expect(screen.queryByRole('article', { name: 'TTM financial statements' })).toBeNull();
    });

    it('rejects a URL frequency mismatch and never exposes a stale report after a current refusal', async () => {
        openSaved('ttm');
        const fetch = vi.fn().mockResolvedValue(json(statementEnvelope('quarter'))); vi.stubGlobal('fetch', fetch);
        render(reader());
        await screen.findByText(/Saved URL frequency differs/);
        expect(screen.queryByRole('article')).toBeNull();
        fetch.mockResolvedValueOnce(json(statementEnvelope('ttm')));
        fireEvent.click(screen.getByRole('button', { name: 'Retry saved report' }));
        await screen.findByRole('article', { name: 'TTM financial statements' });
        fetch.mockResolvedValueOnce(json({ detail: 'Source authorization withdrawn.' }, 403));
        fireEvent(window, new Event('focus'));
        await screen.findByText('Source authorization withdrawn.');
        expect(screen.queryByRole('article')).toBeNull();
    });

    it('rejects a frequency response that silently changes the retained annual/fiscal pair', async () => {
        openSaved('quarter');
        const changed = statementEnvelope('ttm');
        changed.data.statement_read.edition.annual_manifest_digest = '0'.repeat(64);
        vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => Promise.resolve(json(url.endsWith('/read') ? statementReadResponse('ttm', 'changed-pair') : url.includes('changed-pair') ? changed : statementEnvelope('quarter')))));
        render(reader());
        await screen.findByRole('article', { name: 'Quarterly financial statements' });
        fireEvent.click(screen.getByRole('radio', { name: 'TTM' }));
        await screen.findByText(/differs from the requested saved edition/);
        expect(screen.queryByRole('article')).toBeNull();
    });

    it('does not accept a conditional 304 as permission to reuse a saved value', async () => {
        openSaved('quarter');
        const fetch = vi.fn().mockResolvedValue(json(statementEnvelope('quarter'))); vi.stubGlobal('fetch', fetch);
        render(reader());
        await screen.findByRole('article', { name: 'Quarterly financial statements' });
        fetch.mockResolvedValueOnce(new Response(null, { status: 304 }));
        fireEvent(window, new Event('focus'));
        await screen.findByText('Saved statements unavailable (HTTP 304).');
        expect(screen.queryByRole('article')).toBeNull();
        expect(fetch.mock.calls[1][1].headers).toBeUndefined();
        expect(fetch.mock.calls[1][1].cache).toBe('no-store');
    });

    it('retains the new-read creation identity across failure and retry', async () => {
        const intents: string[] = [];
        vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string, init?: RequestInit) => {
            if (url.includes('/artifacts/')) return Promise.resolve(json(statementEnvelope('annual')));
            if (url.endsWith('/catalog')) return Promise.resolve(json(catalog()));
            intents.push(String(init?.body));
            return Promise.resolve(intents.length === 1 ? json({ detail: { code: 'UPSTREAM_UNAVAILABLE', message: 'Read unavailable.', retryable: true } }, 502) : json(statementReadResponse('annual', 'saved-1', 'new-thread')));
        }));
        render(reader(null));
        fireEvent.click(screen.getByRole('combobox', { name: 'Statement company and edition' }));
        fireEvent.click(await screen.findByRole('option', { name: /Example Issuer/ }));
        fireEvent.click(screen.getByRole('button', { name: 'Read prepared statements' }));
        await screen.findByText(/UPSTREAM_UNAVAILABLE/);
        expect(new URLSearchParams(window.location.search).get('statement_creation')).toMatch(/^[0-9a-f-]{36}$/);
        fireEvent.click(screen.getByRole('button', { name: 'Retry statement read' }));
        await screen.findByRole('article', { name: 'Annual financial statements' });
        expect(intents).toHaveLength(2);
        expect(intents[1]).toBe(intents[0]);
    });

    it('uses only returned periods and restores the exact saved artifact on back navigation', async () => {
        openSaved('quarter');
        const fetch = vi.fn().mockImplementation((url: string) => Promise.resolve(json(statementEnvelope(url.includes('saved-ttm') ? 'ttm' : 'quarter')))); vi.stubGlobal('fetch', fetch);
        render(reader());
        await screen.findByRole('article', { name: 'Quarterly financial statements' });
        const period = loadStatementReadFixture('quarter').read;
        if (period.kind !== 'fiscal' || period.result.binding.columns.frequency !== 'quarter') throw new Error('Quarter fixture required');
        const id = period.result.binding.columns.periods[0].period_id;
        fireEvent.change(screen.getByRole('combobox', { name: 'Statement period' }), { target: { value: id } });
        expect(new URLSearchParams(window.location.search).get('statement_period')).toBe(id);
        await act(async () => {
            window.history.pushState({}, '', '/workspace?statement_thread=thread-1&statement_artifact=saved-ttm&statement_frequency=ttm&statement_period=unknown');
            window.dispatchEvent(new PopStateEvent('popstate'));
        });
        await screen.findByRole('article', { name: 'TTM financial statements' });
        expect(screen.getByRole('combobox', { name: 'Statement period' })).toHaveProperty('value', '');
        screen.getByText(/linked period is not present/);
        await act(async () => { window.history.back(); });
        await waitFor(() => expect(screen.getByRole('article', { name: 'Quarterly financial statements' })).toBeTruthy());
        expect(screen.getByRole('combobox', { name: 'Statement period' })).toHaveProperty('value', id);
    });

    it('does not load a statement link belonging to another thread', async () => {
        openSaved('quarter');
        const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
        render(reader('current-thread'));
        await act(async () => { await Promise.resolve(); });
        expect(fetch).not.toHaveBeenCalled();
        expect(screen.queryByRole('article')).toBeNull();
    });
    it('keeps values and inventory hidden after a current frequency refusal until a successful retry', async () => {
        openSaved('quarter');
        const inventory = vi.fn();
        let refused = true;
        const fetch = vi.fn().mockImplementation((url: string) => Promise.resolve(json(url.endsWith('/read')
            ? refused ? { detail: { code: 'FISCAL_RELEASE_INVALID', message: 'Statements could not be read.', retryable: false } } : statementReadResponse('ttm', 'saved-ttm')
            : statementEnvelope(url.includes('saved-ttm') ? 'ttm' : 'quarter'), url.endsWith('/read') && refused ? 502 : 200)));
        vi.stubGlobal('fetch', fetch);
        render(<SWRConfig value={{ provider: () => new Map() }}><StatementReader threadId="thread-1" onEvidenceItems={inventory} /></SWRConfig>);
        await screen.findByRole('article', { name: 'Quarterly financial statements' });
        expect(inventory.mock.lastCall?.[0].length).toBeGreaterThan(0);
        fireEvent.click(screen.getByRole('radio', { name: 'TTM' }));
        await screen.findByText(/FISCAL_RELEASE_INVALID/);
        expect(screen.queryByRole('article')).toBeNull();
        expect(inventory.mock.lastCall?.[0]).toEqual([]);
        fireEvent(window, new Event('focus'));
        await act(async () => { await Promise.resolve(); });
        expect(screen.queryByRole('article')).toBeNull();
        refused = false;
        fireEvent.click(screen.getByRole('button', { name: 'Retry statement read' }));
        await screen.findByRole('article', { name: 'TTM financial statements' });
        expect(inventory.mock.lastCall?.[0].length).toBeGreaterThan(0);
    });

    it.each([
        'statement_thread=thread_%30%35%33a542d-f434-547c-9e23-ebfb9752a9c3&statement_artifact=saved-1&statement_frequency=annual',
        'statement_thread=thread_053a542d-f434-547c-9e23-ebfb9752a9c3&statement_artifact=saved-1&statement_frequency=annual',
    ])('loads the legal encoded and decoded Core thread identity on reload: %s', async (search) => {
        window.history.replaceState(null, '', `/workspace?${search}`);
        const fetch = vi.fn().mockResolvedValue(json(statementEnvelope('annual'))); vi.stubGlobal('fetch', fetch);
        render(reader('thread_053a542d-f434-547c-9e23-ebfb9752a9c3'));
        await screen.findByRole('article', { name: 'Annual financial statements' });
        expect(fetch).toHaveBeenCalledWith('/api/v1/artifacts/saved-1?thread_id=thread_053a542d-f434-547c-9e23-ebfb9752a9c3', expect.objectContaining({ cache: 'no-store' }));
    });

    it.each([
        'statement_thread=thread_1&statement_thread=thread_1&statement_artifact=saved-1',
        `statement_thread=${'a'.repeat(129)}&statement_artifact=saved-1`,
        'statement_thread=thread_%2Fother&statement_artifact=saved-1',
    ])('rejects ambiguous or out-of-profile saved identity: %s', async (search) => {
        window.history.replaceState(null, '', `/workspace?${search}`);
        const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
        render(reader(null));
        await act(async () => { await Promise.resolve(); });
        expect(fetch).not.toHaveBeenCalled();
        expect(screen.queryByRole('article')).toBeNull();
    });

    it('reads a selected edition in an existing normal Core thread', async () => {
        const threadId = 'thread_053a542d-f434-547c-9e23-ebfb9752a9c3';
        const fetch = vi.fn().mockImplementation((url: string) => Promise.resolve(json(url.endsWith('/catalog') ? catalog()
            : url.endsWith('/read') ? statementReadResponse('annual', 'saved-existing', threadId) : statementEnvelope('annual'))));
        vi.stubGlobal('fetch', fetch);
        render(reader(threadId));
        fireEvent.click(screen.getByRole('combobox', { name: 'Statement company and edition' }));
        fireEvent.click(await screen.findByRole('option', { name: /Example Issuer/ }));
        fireEvent.click(screen.getByRole('button', { name: 'Read prepared statements' }));
        await screen.findByRole('article', { name: 'Annual financial statements' });
        expect(fetch).toHaveBeenCalledWith('/api/v1/fundamental/statements/read', expect.objectContaining({ body: JSON.stringify({ contract_version: 'workspace.statement-reader.v2', kind: 'existing_thread', thread_id: threadId, edition_id: loadStatementReadFixture('annual').edition.edition_id, frequency: 'annual' }) }));
    });

    it('rechecks current access before returning from a failed read to the saved version', async () => {
        openSaved('quarter');
        let gets = 0;
        const fetch = vi.fn().mockImplementation((url: string) => {
            if (url.endsWith('/catalog')) return Promise.resolve(json(catalog('quarter')));
            if (url.endsWith('/read')) return Promise.resolve(json({ detail: { code: 'FISCAL_RELEASE_INVALID', message: 'Current release refused.', retryable: false } }, 502));
            return Promise.resolve(++gets === 1 ? json(statementEnvelope('quarter')) : json({ detail: 'Authorization no longer allowed.' }, 403));
        });
        vi.stubGlobal('fetch', fetch);
        render(reader());
        await screen.findByRole('article', { name: 'Quarterly financial statements' });
        fireEvent.click(screen.getByRole('radio', { name: 'TTM' }));
        await screen.findByText(/FISCAL_RELEASE_INVALID/);
        fireEvent.click(screen.getByRole('combobox', { name: 'Statement company and edition' }));
        fireEvent.click(await screen.findByRole('option', { name: /Apple Inc/ }));
        fireEvent.click(screen.getByRole('button', { name: 'Return to saved version' }));
        expect(screen.queryByRole('article')).toBeNull();
        await screen.findByText('Authorization no longer allowed.');
        expect(screen.queryByRole('article')).toBeNull();
        expect(gets).toBeGreaterThan(1);
    });

});
