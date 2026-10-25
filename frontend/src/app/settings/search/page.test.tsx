import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SearchSettingsPage from './page';
import { SearchSettingsApiError } from '@/lib/search-settings-api';

const api = vi.hoisted(() => ({
    addSearchKey: vi.fn(), deleteSearchKey: vi.fn(), getSearchSettings: vi.fn(),
    replaceSearchKey: vi.fn(), setSearchKeyEnabled: vi.fn(), updateSearchSettings: vi.fn(),
}));
const router = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock('@/lib/search-settings-api', () => ({
    ...api,
    SearchSettingsApiError: class SearchSettingsApiError extends Error {
        constructor(message: string, readonly status: number) { super(message); }
    },
}));
vi.mock('next/navigation', () => ({ useRouter: () => router }));

const snapshot = {
    providers: [
        { provider: 'provider-a', operations: ['web', 'news'], key_required: true, optional_fields: [] },
        { provider: 'ddgs', operations: ['web', 'news'], key_required: false, optional_fields: ['region'] },
    ],
    settings: { providers: [
        { provider: 'provider-a', enabled: true, priority: 0, keys: [] },
        { provider: 'ddgs', enabled: true, priority: 1, keys: [] },
    ] },
};

describe('Search settings page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getSearchSettings.mockResolvedValue(snapshot);
        api.addSearchKey.mockResolvedValue({ id: 'key1', provider: 'provider-a', tested: true, active: true, suffix: 'cdef', fingerprint: 'safe-fingerprint' });
        api.updateSearchSettings.mockResolvedValue(snapshot);
        api.deleteSearchKey.mockResolvedValue(undefined);
    });
    afterEach(() => { cleanup(); vi.restoreAllMocks(); });

    it('shows loading, provider availability, empty keys, and does not offer a key form for DDGS', async () => {
        let resolveSettings: (data: typeof snapshot) => void = () => undefined;
        api.getSearchSettings.mockImplementation(() => new Promise((resolve) => { resolveSettings = resolve; }));
        render(<SearchSettingsPage />);
        screen.getByText('Loading Search settings…');
        resolveSettings(snapshot);
        await screen.findAllByText('provider-a');
        screen.getByText('ddgs does not require a key.');
        screen.getByText('No keys configured for this provider.');
        expect(screen.queryByLabelText('API key for ddgs')).toBeNull();
    });

    it('adds the key through the service test-and-save operation and clears its input', async () => {
        render(<SearchSettingsPage />);
        const input = await screen.findByLabelText('Provider API key');
        fireEvent.change(input, { target: { value: 'raw-key-secret' } });
        fireEvent.click(screen.getByRole('button', { name: 'Test and add key' }));
        await screen.findByText('Provider key tested and added.');
        expect(api.addSearchKey).toHaveBeenCalledTimes(1);
        expect(api.addSearchKey).toHaveBeenCalledWith({ provider: 'provider-a', api_key: 'raw-key-secret', label: 'provider-a key' });
        expect(screen.queryByDisplayValue('raw-key-secret')).toBeNull();
    });

    it('does not report success when the service rejects a key and reports service unavailability', async () => {
        api.addSearchKey.mockRejectedValue(new SearchSettingsApiError('provider_key_rejected', 422));
        render(<SearchSettingsPage />);
        fireEvent.change(await screen.findByLabelText('Provider API key'), { target: { value: 'rejected' } });
        fireEvent.click(screen.getByRole('button', { name: 'Test and add key' }));
        await screen.findByText('The provider rejected this setting or key.');
        expect(api.addSearchKey).toHaveBeenCalledTimes(1);

        cleanup();
        api.getSearchSettings.mockRejectedValue(new SearchSettingsApiError('unavailable', 503));
        render(<SearchSettingsPage />);
        await screen.findByText('Search Service is currently unavailable.');
        expect(screen.getByRole('alert')).toBeTruthy();
    });

    it('persists enablement and order from the provider list', async () => {
        render(<SearchSettingsPage />);
        await screen.findAllByText('provider-a');
        fireEvent.click(screen.getByRole('button', { name: 'Move ddgs up' }));
        fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
        await waitFor(() => expect(api.updateSearchSettings).toHaveBeenCalledWith([
            { provider: 'ddgs', enabled: true, priority: 0 },
            { provider: 'provider-a', enabled: true, priority: 1 },
        ]));
    });

    it('requires an explicit dialog action before deleting a key', async () => {
        const keyedSnapshot = {
            ...snapshot,
            settings: { providers: [
                { ...snapshot.settings.providers[0], keys: [{ id: 'key1', provider: 'provider-a', label: 'Main', suffix: 'cdef', fingerprint: 'safe', enabled: true, priority: 0, status: 'active' as const, failure_count: 0, last_tested_at: null, last_used_at: null, cooldown_until: null }] },
                snapshot.settings.providers[1],
            ] },
        };
        api.getSearchSettings.mockResolvedValue(keyedSnapshot);
        render(<SearchSettingsPage />);
        await screen.findByText('Main · •••• cdef');
        fireEvent.click(screen.getByRole('button', { name: 'Delete Main' }));
        expect(api.deleteSearchKey).not.toHaveBeenCalled();
        screen.getByRole('alertdialog');
        fireEvent.click(screen.getByRole('button', { name: 'Delete key' }));
        await waitFor(() => expect(api.deleteSearchKey).toHaveBeenCalledWith('key1'));
        await screen.findByText('Main was deleted.');
    });

    it('keeps the last provider data visible and offers retry when refresh fails', async () => {
        render(<SearchSettingsPage />);
        await screen.findAllByText('provider-a');
        api.getSearchSettings.mockRejectedValueOnce(new Error('network unavailable'));
        fireEvent.click(screen.getByRole('button', { name: 'Refresh Search settings' }));
        await screen.findByText('network unavailable');
        expect(screen.getAllByText('provider-a').length).toBeGreaterThan(0);
        expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy();
    });
});
