import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { useState, useSyncExternalStore } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SWRConfig } from 'swr';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadStatementReadFixture, statementEnvelope, statementReadResponse } from '@/test-fixtures/statement-read';
import { StatementReader } from './outputs/fundamental-analysis/statement-reader';
import { saveStatementReference } from './workspace-statement-location';
import { statementEditionIdentity } from '@/types/agents/statement-read';
import type { WorkspaceRouteIntent } from './workspace-route-intent';

const navigation = vi.hoisted(() => ({ search: '', listeners: new Set<() => void>(), restores: 0 }));
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams(useSyncExternalStore(
    (callback) => { navigation.listeners.add(callback); return () => navigation.listeners.delete(callback); },
    () => navigation.search,
    () => '',
)) }));
vi.mock('@/features/workspace/workspace-page', () => ({
    WorkspacePage: function WorkspacePage({ routeIntent }: { routeIntent: WorkspaceRouteIntent }) {
        const [panel, setPanel] = useState('closed');
        return <div data-testid="workspace" data-mode={routeIntent.kind} data-panel={panel}>
            <button onClick={() => setPanel('open')}>Open workspace panel</button>
            <StatementReader threadId={routeIntent.kind === 'statement-report' ? routeIntent.threadId : null} onEvidenceItems={vi.fn()} />
        </div>;
    },
}));
import { WorkspacePageClient } from '@/app/workspace/WorkspacePageClient';

const nativePush = window.history.pushState;
const nativeReplace = window.history.replaceState;
const nextSource = readFileSync(createRequire(import.meta.url).resolve('next/dist/client/components/app-router.js'), 'utf8');
function installedBlock(start: string, end: string) {
    const first = nextSource.indexOf(start);
    const last = nextSource.indexOf(end, first);
    if (first < 0 || last <= first) throw new Error('Installed Next history wrapper could not be located.');
    return nextSource.slice(first, last + end.length);
}
function installNextHistory() {
    runInNewContext([
        installedBlock('function copyNextJsInternalHistoryState(data)', '\n}'),
        installedBlock('const applyUrlFromHistoryPushReplace = (url)=>{', '\n        };'),
        installedBlock('window.history.pushState = function pushState(data, _unused, url)', '\n        };'),
        installedBlock('window.history.replaceState = function replaceState(data, _unused, url)', '\n        };'),
    ].join('\n'), {
        window, URL,
        originalPushState: nativePush.bind(window.history), originalReplaceState: nativeReplace.bind(window.history),
        _navigator: { restore: (url: URL) => {
            navigation.restores++;
            navigation.search = url.search;
            navigation.listeners.forEach((callback) => callback());
        } },
    });
}
const threadId = 'thread_053a542d-f434-547c-9e23-ebfb9752a9c3';
const json = (value: unknown) => new Response(JSON.stringify(value));
function app() { return <SWRConfig value={{ provider: () => new Map(), shouldRetryOnError: false }}><WorkspacePageClient /></SWRConfig>; }
async function createRead() {
    fireEvent.click(screen.getByRole('combobox', { name: 'Statement company and edition' }));
    fireEvent.click(await screen.findByRole('option', { name: /Example Issuer/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Read prepared statements' }));
}
beforeEach(() => {
    nativeReplace.call(window.history, { __NA: true, __PRIVATE_NEXTJS_INTERNALS_TREE: { retained: 'installed-next-tree' } }, '', '/workspace');
    navigation.search = ''; navigation.restores = 0;
    installNextHistory();
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
    HTMLElement.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
    cleanup(); vi.unstubAllGlobals();
    window.history.pushState = nativePush; window.history.replaceState = nativeReplace;
    nativeReplace.call(window.history, null, '', '/workspace');
    navigation.listeners.clear();
});

describe('statement URL with installed Next history integration', () => {
    it('synchronizes new to statement remount and retains the POST edition expectation on remount and reload', async () => {
        const edition = loadStatementReadFixture('annual').edition;
        const changed = statementEnvelope('annual');
        changed.data.statement_read.edition.fiscal_manifest_digest = '0'.repeat(64);
        const fetch = vi.fn().mockImplementation((url: string) => Promise.resolve(json(url.endsWith('/catalog')
            ? { contract_version: 'workspace.statement-reader.v2', entries: [edition] }
            : url.endsWith('/read') ? statementReadResponse('annual', 'saved-1', threadId) : changed)));
        vi.stubGlobal('fetch', fetch);
        const view = render(app());
        fireEvent.click(screen.getByRole('button', { name: 'Open workspace panel' }));
        await createRead();
        await screen.findByText(/differs from the requested saved edition/);
        expect(screen.getByTestId('workspace').getAttribute('data-mode')).toBe('statement-report');
        expect(screen.getByTestId('workspace').getAttribute('data-panel')).toBe('closed');
        expect(navigation.restores).toBeGreaterThanOrEqual(2);
        expect(screen.queryByRole('article')).toBeNull();
        view.unmount();
        render(app());
        await screen.findByText(/differs from the requested saved edition/);
        expect(fetch).toHaveBeenCalledWith(`/api/v1/artifacts/saved-1?thread_id=${threadId}`, expect.objectContaining({ cache: 'no-store' }));
    });

    it('retains same-thread workspace state for frequency and period, and resets when thread changes', async () => {
        const edition = loadStatementReadFixture('quarter').edition;
        vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => Promise.resolve(json(url.endsWith('/catalog')
            ? { contract_version: 'workspace.statement-reader.v2', entries: [edition] }
            : url.endsWith('/read') ? statementReadResponse('ttm', 'saved-ttm', threadId)
            : statementEnvelope(url.includes('saved-ttm') ? 'ttm' : url.includes('other') ? 'annual' : 'quarter')))));
        await act(async () => saveStatementReference({ threadId, artifactId: 'saved-1', editionIdentity: statementEditionIdentity(edition) }, 'quarter'));
        const entry: unknown = window.history.state;
        expect(entry).toHaveProperty('__NA', true);
        render(app());
        await screen.findByRole('article', { name: 'Quarterly financial statements' });
        fireEvent.click(screen.getByRole('button', { name: 'Open workspace panel' }));
        fireEvent.change(screen.getByRole('combobox', { name: 'Statement period' }), { target: { value: screen.getByRole('combobox', { name: 'Statement period' }).querySelectorAll('option')[1]?.value } });
        expect(screen.getByTestId('workspace').getAttribute('data-panel')).toBe('open');
        fireEvent.click(screen.getByRole('radio', { name: 'TTM' }));
        await screen.findByRole('article', { name: 'TTM financial statements' });
        expect(screen.getByTestId('workspace').getAttribute('data-panel')).toBe('open');
        await act(async () => window.history.pushState(null, '', '/workspace?statement_thread=thread_other&statement_artifact=other&statement_frequency=annual'));
        await waitFor(() => expect(screen.getByTestId('workspace').getAttribute('data-panel')).toBe('closed'));
        await screen.findByRole('article', { name: 'Annual financial statements' });
    });

    it.each([null, { threadId: 'thread_other', artifactId: 'saved-1', editionIdentity: 'old' }])('refuses malformed or mismatched app history identity: %j', async (expectation) => {
        await act(async () => window.history.pushState({ statementReadExpectation: expectation }, '', `/workspace?statement_thread=${threadId}&statement_artifact=saved-1&statement_frequency=annual`));
        const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
        render(app());
        await screen.findByText(/history identity is invalid/);
        expect(screen.queryByRole('article')).toBeNull();
        expect(fetch).not.toHaveBeenCalled();
    });
});
