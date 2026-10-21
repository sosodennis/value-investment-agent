import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import LlmKeysPage from './page';

const api = vi.hoisted(() => ({
    addOpenRouterKey: vi.fn(),
    createLocalAdminSession: vi.fn(),
    deleteOpenRouterKey: vi.fn(),
    getLlmSettings: vi.fn(),
    listOpenRouterKeys: vi.fn(),
    testOpenRouterKey: vi.fn(),
    updateLlmSettings: vi.fn(),
}));

const existingKey = {
    id: 'managed-1',
    label: 'Primary key',
    suffix: 'cdef',
    fingerprint: 'f00dbabe1234',
    created_at: '2026-10-21T00:00:00Z',
};

vi.mock('@/lib/llm-provider-api', () => ({
    ...api,
    LlmProviderApiError: class LlmProviderApiError extends Error {},
}));

describe('OpenRouter key settings', () => {
    afterEach(() => {
        cleanup();
        vi.restoreAllMocks();
    });

    beforeEach(() => {
        vi.clearAllMocks();
        api.createLocalAdminSession.mockResolvedValue(undefined);
        api.listOpenRouterKeys.mockResolvedValue([]);
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
        api.addOpenRouterKey.mockResolvedValue({
            id: 'managed-1',
            label: 'Primary key',
            suffix: 'cdef',
            fingerprint: 'f00dbabe1234',
            created_at: '2026-10-21T00:00:00Z',
        });
    });

    it('starts a local admin session and clears the one-time key after adding', async () => {
        render(<LlmKeysPage />);
        await waitFor(() => expect(api.createLocalAdminSession).toHaveBeenCalledOnce());
        await waitFor(() => expect(api.listOpenRouterKeys).toHaveBeenCalledWith());

        fireEvent.change(screen.getByLabelText('Label'), {
            target: { value: 'Primary key' },
        });
        fireEvent.change(screen.getByLabelText('OpenRouter API key'), {
            target: { value: 'sk-or-v1-test-openrouter-secret' },
        });
        fireEvent.click(screen.getByRole('button', { name: 'Test and add key' }));

        await screen.findByText('Primary key');
        expect(screen.getByText('Configured')).toBeTruthy();
        expect(api.addOpenRouterKey).toHaveBeenCalledWith({
            label: 'Primary key',
            api_key: 'sk-or-v1-test-openrouter-secret',
        });
        expect(screen.queryByDisplayValue('sk-or-v1-test-openrouter-secret')).toBeNull();
    });

    it('tests a configured key and reports the result', async () => {
        api.listOpenRouterKeys.mockResolvedValue([existingKey]);
        api.testOpenRouterKey.mockResolvedValue({
            id: existingKey.id,
            passed: true,
            status: 'healthy',
        });
        render(<LlmKeysPage />);
        await screen.findByText(existingKey.label);
        fireEvent.click(screen.getByRole('button', { name: 'Test' }));

        expect(await screen.findByText('Primary key is healthy.')).toBeTruthy();
        expect(api.testOpenRouterKey).toHaveBeenCalledWith(existingKey.id);
    });

    it('deletes a configured key after confirmation', async () => {
        api.listOpenRouterKeys.mockResolvedValue([existingKey]);
        api.deleteOpenRouterKey.mockResolvedValue(undefined);
        const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
        render(<LlmKeysPage />);
        await screen.findByText(existingKey.label);
        fireEvent.click(screen.getByRole('button', { name: 'Delete Primary key' }));

        expect(await screen.findByText('Primary key was deleted.')).toBeTruthy();
        expect(api.deleteOpenRouterKey).toHaveBeenCalledWith(existingKey.id);
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

        render(<LlmKeysPage />);
        const picker = await screen.findByRole('button', { name: 'Default OpenRouter model' });
        fireEvent.click(picker);
        fireEvent.click(await screen.findByRole('option', { name: /Example Free Model/ }));

        await waitFor(() => expect(api.updateLlmSettings).toHaveBeenCalledWith('provider/example:free'));
        expect(await screen.findByText('Default model changed to provider/example:free.')).toBeTruthy();
    });
});
