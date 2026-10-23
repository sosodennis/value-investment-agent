import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SearchSettingsPage from './page';
import { SearchSettingsApiError } from '@/lib/search-settings-api';

const api = vi.hoisted(() => ({
    addSearchKey: vi.fn(), deleteSearchKey: vi.fn(), getSearchSettings: vi.fn(),
    replaceSearchKey: vi.fn(), testSearchKey: vi.fn(), updateSearchSettings: vi.fn(),
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
        { provider: 'provider-a', enabled: true, priority: 0, key: null },
        { provider: 'ddgs', enabled: true, priority: 1, key: null },
    ] },
};

describe('Search settings page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getSearchSettings.mockResolvedValue(snapshot);
        api.testSearchKey.mockResolvedValue({ provider: 'provider-a', valid: true, status: 'valid' });
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
        screen.getByText('No key configured');
        expect(screen.queryByLabelText('API key for ddgs')).toBeNull();
    });

    it('tests a key before adding and clears its input after activation', async () => {
        render(<SearchSettingsPage />);
        const input = await screen.findByLabelText('Search provider API key');
        fireEvent.change(input, { target: { value: 'raw-key-secret' } });
        fireEvent.click(screen.getByRole('button', { name: 'Test and add' }));
        await screen.findByText('Provider key tested and added.');
        expect(api.testSearchKey).toHaveBeenCalledWith({ provider: 'provider-a', api_key: 'raw-key-secret' });
        expect(api.addSearchKey).toHaveBeenCalledWith({ provider: 'provider-a', api_key: 'raw-key-secret', label: 'provider-a key' });
        expect(screen.queryByDisplayValue('raw-key-secret')).toBeNull();
    });

    it('does not activate an invalid key and reports service unavailability', async () => {
        api.testSearchKey.mockResolvedValue({ provider: 'provider-a', valid: false, status: 'invalid' });
        render(<SearchSettingsPage />);
        fireEvent.change(await screen.findByLabelText('Search provider API key'), { target: { value: 'rejected' } });
        fireEvent.click(screen.getByRole('button', { name: 'Test and add' }));
        await screen.findByText('The provider rejected this key. The key was not saved.');
        expect(api.addSearchKey).not.toHaveBeenCalled();

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
});
