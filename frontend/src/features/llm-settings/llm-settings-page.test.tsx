import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LlmSettingsApiError } from './api';
import LlmSettingsPage from './llm-settings-page';

const api = vi.hoisted(() => ({
    addLlmProviderKey: vi.fn(),
    createLlmProviderKeyImport: vi.fn(),
    deleteLlmProviderKey: vi.fn(),
    getLlmProviderKeyImport: vi.fn(),
    getLlmSettings: vi.fn(),
    listLlmProviderKeys: vi.fn(),
    listLlmProviderKeyImports: vi.fn(),
    previewLlmProviderKeyImport: vi.fn(),
    replaceLlmProviderKey: vi.fn(),
    retryLlmProviderKeyImport: vi.fn(),
    testLlmProviderKey: vi.fn(),
    updateLlmSettings: vi.fn(),
}));

const router = vi.hoisted(() => ({ replace: vi.fn() }));

const existingKey = {
    id: 'managed-1',
    label: 'Primary key',
    suffix: 'cdef',
    fingerprint: 'f00dbabe1234',
    created_at: '2026-10-21T00:00:00Z',
};

function deferred<T>() {
    let resolvePromise: (value: T) => void = () => {
        throw new Error('deferred promise was not initialized');
    };
    const promise = new Promise<T>((resolve) => {
        resolvePromise = resolve;
    });
    return { promise, resolve: (value: T) => resolvePromise(value) };
}

vi.mock('@/features/llm-settings/api', () => ({
    ...api,
    LlmSettingsApiError: class LlmSettingsApiError extends Error {
        status: number;

        constructor(message: string, status: number) {
            super(message);
            this.status = status;
        }
    },
}));

vi.mock('next/navigation', () => ({
    useRouter: () => router,
}));

describe('LLM settings', () => {
    afterEach(() => {
        cleanup();
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
        Reflect.deleteProperty(Element.prototype, 'scrollIntoView');
    });

    beforeEach(() => {
        vi.clearAllMocks();
        sessionStorage.clear();
        api.listLlmProviderKeys.mockResolvedValue([]);
        api.listLlmProviderKeyImports.mockResolvedValue([]);
        api.getLlmSettings.mockResolvedValue({
            selected_model: 'openrouter/free',
            default_model: 'openrouter/free',
            models: [{
                id: 'openrouter/free',
                name: 'Free Models Router',
                description: 'Selects a free model.',
                context_length: null,
            }],
        });
        api.previewLlmProviderKeyImport.mockResolvedValue({
            file_type: 'txt',
            row_count: 0,
            unique_count: 0,
            duplicate_count: 0,
            issues: [],
        });
        api.addLlmProviderKey.mockResolvedValue({
            id: 'managed-1',
            label: 'Primary key',
            suffix: 'cdef',
            fingerprint: 'f00dbabe1234',
            created_at: '2026-10-21T00:00:00Z',
            status: 'healthy',
            failure_count: 0,
        });
    });

    it('loads the signed-in settings session and clears the one-time key after adding', async () => {
        const pendingAdd = deferred<{
            id: string;
            label: string;
            suffix: string;
            fingerprint: string;
            created_at: string;
            status: string;
            failure_count: number;
        }>();
        api.addLlmProviderKey.mockReturnValue(pendingAdd.promise);
        render(<LlmSettingsPage />);
        await waitFor(() => expect(api.listLlmProviderKeys).toHaveBeenCalledWith());

        fireEvent.change(screen.getByLabelText('Label'), {
            target: { value: 'Primary key' },
        });
        fireEvent.change(screen.getByLabelText('OpenRouter API key'), {
            target: { value: 'sk-or-v1-test-openrouter-secret' },
        });
        fireEvent.click(screen.getByRole('button', { name: 'Test and add key' }));
        const pendingButton = screen.getByRole('button', { name: 'Testing and adding...' });
        expect(pendingButton.hasAttribute('disabled')).toBe(true);

        pendingAdd.resolve({
            id: 'managed-1',
            label: 'Primary key',
            suffix: 'cdef',
            fingerprint: 'f00dbabe1234',
            created_at: '2026-10-21T00:00:00Z',
            status: 'healthy',
            failure_count: 0,
        });

        await screen.findByText('Primary key');
        screen.getByText('Healthy');
        expect(api.addLlmProviderKey).toHaveBeenCalledWith({
            label: 'Primary key',
            api_key: 'sk-or-v1-test-openrouter-secret',
        });
        expect(screen.queryByDisplayValue('sk-or-v1-test-openrouter-secret')).toBeNull();
    });

    it('keeps the model catalogue available when key loading fails and retries keys independently', async () => {
        api.listLlmProviderKeys
            .mockRejectedValueOnce(new Error('temporary key service failure'))
            .mockResolvedValueOnce([existingKey]);
        render(<LlmSettingsPage />);

        await screen.findByText('Could not load provider keys.');
        expect(screen.getByRole('combobox', { name: 'Default OpenRouter model' }).hasAttribute('disabled')).toBe(false);
        fireEvent.click(screen.getByRole('button', { name: 'Retry keys' }));
        await screen.findByText(existingKey.label);
        expect(api.listLlmProviderKeys).toHaveBeenCalledTimes(2);
    });

    it('shows an explicit empty state when the provider catalog has no models', async () => {
        api.getLlmSettings.mockResolvedValue({
            selected_model: 'openrouter/free',
            default_model: 'openrouter/free',
            models: [],
        });
        render(<LlmSettingsPage />);

        await screen.findByText('No free models available');
        expect(screen.getByRole('combobox', { name: 'Default OpenRouter model' }).hasAttribute('disabled')).toBe(true);
    });

    it('tests a configured key and reports the result', async () => {
        const pendingTest = deferred<{ id: string; passed: boolean; status: 'healthy' }>();
        api.listLlmProviderKeys.mockResolvedValue([existingKey]);
        api.testLlmProviderKey.mockReturnValue(pendingTest.promise);
        render(<LlmSettingsPage />);
        await screen.findByText(existingKey.label);
        fireEvent.click(screen.getByRole('button', { name: 'Test' }));
        const pendingButton = screen.getByRole('button', { name: 'Testing...' });
        expect(pendingButton.hasAttribute('disabled')).toBe(true);

        pendingTest.resolve({ id: existingKey.id, passed: true, status: 'healthy' });

        await screen.findByText('Primary key is healthy.');
        expect(api.testLlmProviderKey).toHaveBeenCalledWith(existingKey.id);
    });

    it('shows per-key cooldown and outcomes from normal agent requests', async () => {
        api.listLlmProviderKeys.mockResolvedValue([{
            ...existingKey,
            status: 'cooldown',
            failure_count: 2,
            cooldown_until: '2099-10-21T00:00:00Z',
            last_error: 'rate_limited',
            last_used_at: '2026-10-21T00:00:00Z',
        }]);
        render(<LlmSettingsPage />);

        await screen.findByText('Cooling down');
        screen.getByText(/2 failures/);
        screen.getByText('The provider rate limited this key.');
    });

    it('deletes a configured key only after explicit dialog confirmation', async () => {
        const pendingDelete = deferred<void>();
        api.listLlmProviderKeys.mockResolvedValue([existingKey]);
        api.deleteLlmProviderKey.mockReturnValue(pendingDelete.promise);
        render(<LlmSettingsPage />);
        await screen.findByText(existingKey.label);
        fireEvent.click(screen.getByRole('button', { name: 'Delete Primary key' }));

        expect(api.deleteLlmProviderKey).not.toHaveBeenCalled();
        expect(screen.getByRole('alertdialog').textContent).toContain('Delete Primary key?');
        fireEvent.click(screen.getByRole('button', { name: 'Delete key' }));
        expect(screen.getByRole('button', { name: 'Delete Primary key' }).hasAttribute('disabled')).toBe(true);

        pendingDelete.resolve(undefined);

        await screen.findByText('Primary key was deleted.');
        expect(api.deleteLlmProviderKey).toHaveBeenCalledWith(existingKey.id);
        expect(screen.queryByText(existingKey.label)).toBeNull();
    });

    it('tests and replaces a configured key in place', async () => {
        const pendingReplacement = deferred<{
            id: string;
            label: string;
            suffix: string;
            fingerprint: string;
            created_at: string;
            status: string;
            failure_count: number;
        }>();
        api.listLlmProviderKeys.mockResolvedValue([existingKey]);
        api.replaceLlmProviderKey.mockReturnValue(pendingReplacement.promise);
        render(<LlmSettingsPage />);
        await screen.findByText(existingKey.label);

        fireEvent.click(screen.getByRole('button', { name: 'Replace' }));
        expect((screen.getByLabelText('Label') as HTMLInputElement).value).toBe(existingKey.label);
        fireEvent.change(screen.getByLabelText('OpenRouter API key'), {
            target: { value: 'sk-or-v1-replacement-secret' },
        });
        fireEvent.click(screen.getByRole('button', { name: 'Test and replace key' }));
        const pendingButton = screen.getByRole('button', { name: 'Testing and replacing...' });
        expect(pendingButton.hasAttribute('disabled')).toBe(true);
        expect(screen.getByLabelText('OpenRouter API key').hasAttribute('disabled')).toBe(true);

        pendingReplacement.resolve({
            ...existingKey,
            suffix: '9876',
            status: 'healthy',
            failure_count: 0,
        });

        await screen.findByText(/passed its test and replaced Primary key/);
        expect(api.replaceLlmProviderKey).toHaveBeenCalledWith(existingKey.id, {
            label: existingKey.label,
            api_key: 'sk-or-v1-replacement-secret',
        });
        expect(screen.getByText('sk-or-••••9876')).toBeTruthy();
        expect(screen.queryByDisplayValue('sk-or-v1-replacement-secret')).toBeNull();
    });

    it('shows an actionable error and keeps the current key when replacement is rejected', async () => {
        api.listLlmProviderKeys.mockResolvedValue([existingKey]);
        api.replaceLlmProviderKey.mockRejectedValue(new LlmSettingsApiError(
            'replacement key must differ from the current key',
            400,
        ));
        render(<LlmSettingsPage />);
        await screen.findByText(existingKey.label);

        fireEvent.click(screen.getByRole('button', { name: 'Replace' }));
        fireEvent.change(screen.getByLabelText('OpenRouter API key'), {
            target: { value: 'sk-or-v1-same-replacement-key' },
        });
        fireEvent.click(screen.getByRole('button', { name: 'Test and replace key' }));

        await screen.findByText('replacement key must differ from the current key');
        expect(screen.getByText(existingKey.label)).toBeTruthy();
        expect(screen.queryByText(/passed its test and replaced/)).toBeNull();
    });

    it('updates the global model policy from the free model picker', async () => {
        vi.stubGlobal('ResizeObserver', class {
            observe() {}
            unobserve() {}
            disconnect() {}
        });
        Object.defineProperty(Element.prototype, 'scrollIntoView', {
            configurable: true,
            value: vi.fn(),
        });
        api.getLlmSettings.mockResolvedValue({
            selected_model: 'openrouter/free',
            default_model: 'openrouter/free',
            models: [
                {
                    id: 'openrouter/free',
                    name: 'Free Models Router',
                    description: 'Selects a free model.',
                    context_length: null,
                },
                {
                    id: 'provider/example:free',
                    name: 'Example Free Model',
                    description: 'A concrete free model.',
                    context_length: 8192,
                },
            ],
        });
        const updatedSettings = {
            selected_model: 'provider/example:free',
            default_model: 'openrouter/free',
            models: [
                {
                    id: 'openrouter/free',
                    name: 'Free Models Router',
                    description: 'Selects a free model.',
                    context_length: null,
                },
                {
                    id: 'provider/example:free',
                    name: 'Example Free Model',
                    description: 'A concrete free model.',
                    context_length: 8192,
                },
            ],
        };
        const pendingSave = deferred<typeof updatedSettings>();
        api.updateLlmSettings.mockReturnValue(pendingSave.promise);

        render(<LlmSettingsPage />);
        const picker = await screen.findByRole('combobox', { name: 'Default OpenRouter model' });
        fireEvent.click(picker);
        fireEvent.click(await screen.findByRole('option', { name: /Example Free Model/ }));
        expect(screen.getByText('Saving model')).toBeTruthy();
        expect(picker.hasAttribute('disabled')).toBe(true);

        pendingSave.resolve(updatedSettings);

        await waitFor(() => expect(api.updateLlmSettings).toHaveBeenCalledWith('provider/example:free'));
        await screen.findByText('Default model changed to provider/example:free.');
    });

    it('redirects expired sessions and preserves only the non-secret label draft', async () => {
        const error = new LlmSettingsApiError(
            'authentication is required',
            401,
        );
        api.listLlmProviderKeys.mockRejectedValue(error);
        const firstRender = render(<LlmSettingsPage />);
        fireEvent.change(screen.getByLabelText('Label'), {
            target: { value: 'Keep this label' },
        });

        await waitFor(() =>
            expect(router.replace).toHaveBeenCalledWith(
                '/login?next=%2Fsettings%2Fllm',
            ),
        );
        expect(sessionStorage.getItem('llm-settings-label-draft')).toBe(
            'Keep this label',
        );
        expect(sessionStorage.getItem('openrouter-api-key')).toBeNull();

        firstRender.unmount();
        api.listLlmProviderKeys.mockResolvedValue([]);
        render(<LlmSettingsPage />);
        await waitFor(() =>
            expect(
                (screen.getByLabelText('Label') as HTMLInputElement).value,
            ).toBe('Keep this label'),
        );
        fireEvent.focus(screen.getByLabelText('Label'));
        expect(sessionStorage.getItem('llm-settings-label-draft')).toBeNull();
    });
});
