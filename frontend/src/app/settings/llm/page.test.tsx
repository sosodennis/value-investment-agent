import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LlmSettingsApiError } from '@/lib/llm-settings-api';
import LlmSettingsPage from './page';

const api = vi.hoisted(() => ({
    addLlmProviderKey: vi.fn(),
    deleteLlmProviderKey: vi.fn(),
    getLlmSettings: vi.fn(),
    listLlmProviderKeys: vi.fn(),
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

vi.mock('@/lib/llm-settings-api', () => ({
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
    });

    beforeEach(() => {
        vi.clearAllMocks();
        sessionStorage.clear();
        api.listLlmProviderKeys.mockResolvedValue([]);
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
        render(<LlmSettingsPage />);
        await waitFor(() => expect(api.listLlmProviderKeys).toHaveBeenCalledWith());

        fireEvent.change(screen.getByLabelText('Label'), {
            target: { value: 'Primary key' },
        });
        fireEvent.change(screen.getByLabelText('OpenRouter API key'), {
            target: { value: 'sk-or-v1-test-openrouter-secret' },
        });
        fireEvent.click(screen.getByRole('button', { name: 'Test and add key' }));

        await screen.findByText('Primary key');
        screen.getByText('Healthy');
        expect(api.addLlmProviderKey).toHaveBeenCalledWith({
            label: 'Primary key',
            api_key: 'sk-or-v1-test-openrouter-secret',
        });
        expect(screen.queryByDisplayValue('sk-or-v1-test-openrouter-secret')).toBeNull();
    });

    it('tests a configured key and reports the result', async () => {
        api.listLlmProviderKeys.mockResolvedValue([existingKey]);
        api.testLlmProviderKey.mockResolvedValue({
            id: existingKey.id,
            passed: true,
            status: 'healthy',
        });
        render(<LlmSettingsPage />);
        await screen.findByText(existingKey.label);
        fireEvent.click(screen.getByRole('button', { name: 'Test' }));

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
        screen.getByText(/2 failures since last success/);
        screen.getByText('The provider rate limited this key.');
    });

    it('deletes a configured key after confirmation', async () => {
        api.listLlmProviderKeys.mockResolvedValue([existingKey]);
        api.deleteLlmProviderKey.mockResolvedValue(undefined);
        const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
        render(<LlmSettingsPage />);
        await screen.findByText(existingKey.label);
        fireEvent.click(screen.getByRole('button', { name: 'Delete Primary key' }));

        await screen.findByText('Primary key was deleted.');
        expect(api.deleteLlmProviderKey).toHaveBeenCalledWith(existingKey.id);
        expect(confirm).toHaveBeenCalledOnce();
        expect(screen.queryByText(existingKey.label)).toBeNull();
    });

    it('updates the global model policy from the free model picker', async () => {
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
        api.updateLlmSettings.mockResolvedValue({
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
        });

        render(<LlmSettingsPage />);
        const picker = await screen.findByRole('button', { name: 'Default OpenRouter model' });
        fireEvent.click(picker);
        fireEvent.click(await screen.findByRole('option', { name: /Example Free Model/ }));

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
        expect(sessionStorage.getItem('llm-settings-label-draft')).toBeNull();
    });
});
