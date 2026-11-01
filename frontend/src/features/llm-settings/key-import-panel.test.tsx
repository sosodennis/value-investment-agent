import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
    createLlmProviderKeyImport: vi.fn(),
    getLlmProviderKeyImport: vi.fn(),
    listLlmProviderKeyImports: vi.fn(),
    previewLlmProviderKeyImport: vi.fn(),
    retryLlmProviderKeyImport: vi.fn(),
}));

vi.mock('@/features/llm-settings/api', () => ({
    ...api,
    LlmSettingsApiError: class LlmSettingsApiError extends Error {
        status: number;
        code: string | null;

        constructor(message: string, status: number, code: string | null = null) {
            super(message);
            this.code = code;
            this.status = status;
        }
    },
}));

import { KeyImportPanel } from './key-import-panel';
import type { LlmProviderKeyImport } from './api';

const preview = {
    file_type: 'txt' as const,
    row_count: 1,
    unique_count: 1,
    duplicate_count: 0,
    issues: [],
};

function batch(
    overrides: Partial<LlmProviderKeyImport> = {},
): LlmProviderKeyImport {
    return {
        id: 'batch-1',
        status: 'queued',
        total_count: 1,
        processed_count: 0,
        imported_count: 0,
        duplicate_count: 0,
        invalid_count: 0,
        retryable_count: 0,
        created_at: '2026-10-31T00:00:00Z',
        updated_at: '2026-10-31T00:00:00Z',
        items: [{
            source_line: 1,
            label: 'OpenRouter key 1',
            suffix: '0001',
            status: 'queued',
            attempts: 0,
            retryable: false,
        }],
        ...overrides,
    };
}

describe('KeyImportPanel', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.listLlmProviderKeyImports.mockResolvedValue([]);
        api.previewLlmProviderKeyImport.mockResolvedValue(preview);
        api.createLlmProviderKeyImport.mockResolvedValue(batch());
        api.getLlmProviderKeyImport.mockResolvedValue(batch({
            status: 'completed',
            processed_count: 1,
            imported_count: 1,
            items: [{
                source_line: 1,
                label: 'OpenRouter key 1',
                suffix: '0001',
                status: 'imported',
                attempts: 1,
                retryable: false,
            }],
        }));
        api.retryLlmProviderKeyImport.mockResolvedValue(batch());
    });

    afterEach(() => {
        cleanup();
        vi.useRealTimers();
    });

    it('previews a file, submits it, and refreshes its per-key result', async () => {
        const onImportCompleted = vi.fn();
        render(
            <KeyImportPanel
                authenticated
                canMutate
                onUnauthorized={() => false}
                submittedImports={[]}
                onImportCompleted={onImportCompleted}
            />,
        );
        await screen.findByText('No key imports yet.');

        const file = new File(['sk-or-v1-fake-key-value-00000001'], 'keys.txt');
        fireEvent.change(screen.getByLabelText('Key file'), { target: { files: [file] } });
        await screen.findByText('1 rows · 1 unique keys · 0 duplicate rows');
        fireEvent.click(screen.getByRole('button', { name: 'Import keys' }));
        await screen.findByText('Queued');
        expect(api.createLlmProviderKeyImport).toHaveBeenCalledWith(file, expect.any(String));

        await waitFor(() => {
            expect(api.getLlmProviderKeyImport).toHaveBeenCalledWith('batch-1');
        }, { timeout: 4000, interval: 100 });
        await waitFor(() => {
            expect(screen.getByText('Completed')).toBeTruthy();
        });
        expect(onImportCompleted).toHaveBeenCalledOnce();
        fireEvent.click(screen.getByText('View per-key results'));
        expect(screen.getByText('Imported')).toBeTruthy();
        expect(screen.getByText('1 imported · 0 duplicates · 0 failed')).toBeTruthy();
    });

    it('allows clearing a selected file and retrying retryable batch items', async () => {
        api.listLlmProviderKeyImports.mockResolvedValue([batch({
            status: 'completed_with_errors',
            processed_count: 1,
            invalid_count: 1,
            retryable_count: 1,
            items: [{
                source_line: 1,
                label: 'OpenRouter key 1',
                suffix: '0001',
                status: 'unavailable',
                attempts: 3,
                retryable: true,
                error_code: 'rate_limited',
            }],
        })]);
        api.retryLlmProviderKeyImport.mockResolvedValue(batch({
            status: 'processing',
            updated_at: '2026-10-31T00:00:01Z',
        }));
        render(
            <KeyImportPanel
                authenticated
                canMutate
                onUnauthorized={() => false}
                submittedImports={[]}
                onImportCompleted={vi.fn()}
            />,
        );
        await screen.findByRole('button', { name: 'Retry 1' });
        fireEvent.click(screen.getByRole('button', { name: 'Retry 1' }));
        await screen.findByText('Processing');
        expect(api.retryLlmProviderKeyImport).toHaveBeenCalledWith('batch-1');

        const file = new File(['sk-or-v1-fake-key-value-00000001'], 'keys.txt');
        fireEvent.change(screen.getByLabelText('Key file'), { target: { files: [file] } });
        await screen.findByText('1 rows · 1 unique keys · 0 duplicate rows');
        fireEvent.click(screen.getByRole('button', { name: 'Clear selected file' }));
        await waitFor(() => {
            expect(screen.queryByText('1 rows · 1 unique keys · 0 duplicate rows')).toBeNull();
            expect((screen.getByLabelText('Key file') as HTMLInputElement).value).toBe('');
            expect(screen.getByRole('button', { name: 'Import keys' }).hasAttribute('disabled')).toBe(true);
        });
    });

    it('shows and tracks a manually submitted one-key import', async () => {
        const onImportCompleted = vi.fn();
        const submittedImport = batch({ id: 'manual-batch-1' });
        api.getLlmProviderKeyImport.mockResolvedValue(batch({
            id: 'manual-batch-1',
            status: 'completed',
            processed_count: 1,
            imported_count: 1,
            items: [{
                source_line: 1,
                label: 'Manual key',
                suffix: '0001',
                status: 'imported',
                attempts: 1,
                retryable: false,
            }],
        }));
        render(
            <KeyImportPanel
                authenticated
                canMutate
                onUnauthorized={() => false}
                submittedImports={[submittedImport]}
                onImportCompleted={onImportCompleted}
            />,
        );

        await screen.findByText('Queued');
        await waitFor(() => {
            expect(api.getLlmProviderKeyImport).toHaveBeenCalledWith('manual-batch-1');
            expect(onImportCompleted).toHaveBeenCalledOnce();
        }, { timeout: 4000, interval: 100 });
        await screen.findByText('Completed');
    });

    it('resumes active history and refreshes keys when an imported batch completes', async () => {
        const onImportCompleted = vi.fn();
        api.listLlmProviderKeyImports.mockResolvedValue([batch({ id: 'resumed-batch' })]);
        api.getLlmProviderKeyImport.mockResolvedValue(batch({
            id: 'resumed-batch',
            status: 'completed',
            processed_count: 1,
            imported_count: 1,
            items: [{
                source_line: 1,
                label: 'OpenRouter key 1',
                suffix: '0001',
                status: 'imported',
                attempts: 1,
                retryable: false,
            }],
        }));
        render(
            <KeyImportPanel
                authenticated
                canMutate
                onUnauthorized={() => false}
                submittedImports={[]}
                onImportCompleted={onImportCompleted}
            />,
        );

        await screen.findByText('Queued');
        await waitFor(() => {
            expect(api.getLlmProviderKeyImport).toHaveBeenCalledWith('resumed-batch');
            expect(onImportCompleted).toHaveBeenCalledOnce();
        }, { timeout: 4000, interval: 100 });
        await screen.findByText('Completed');
    });

    it('keeps earlier manual imports in progress after another is submitted', async () => {
        const props = {
            authenticated: true,
            canMutate: true,
            onUnauthorized: () => false,
            onImportCompleted: vi.fn(),
        };
        const first = batch({ id: 'manual-batch-1' });
        const second = batch({
            id: 'manual-batch-2',
            created_at: '2026-10-31T00:00:01Z',
            updated_at: '2026-10-31T00:00:01Z',
        });
        api.getLlmProviderKeyImport.mockImplementation(async (id: string) => batch({
            id,
            status: 'processing',
            updated_at: '2026-10-31T00:00:02Z',
        }));
        const { rerender } = render(
            <KeyImportPanel {...props} submittedImports={[first]} />,
        );

        await screen.findByText('Queued');
        rerender(<KeyImportPanel {...props} submittedImports={[second, first]} />);

        await waitFor(() => {
            expect(api.getLlmProviderKeyImport).toHaveBeenCalledWith('manual-batch-1');
            expect(api.getLlmProviderKeyImport).toHaveBeenCalledWith('manual-batch-2');
        }, { timeout: 4000, interval: 100 });
        await waitFor(() => {
            expect(screen.getAllByText('Processing')).toHaveLength(2);
        });
    });

    it('allows members to read import history but disables key uploads and retries', async () => {
        api.listLlmProviderKeyImports.mockResolvedValue([batch({
            status: 'completed_with_errors',
            processed_count: 1,
            invalid_count: 1,
            retryable_count: 1,
            items: [{
                source_line: 1,
                label: 'OpenRouter key 1',
                suffix: '0001',
                status: 'unavailable',
                attempts: 3,
                retryable: true,
            }],
        })]);
        render(
            <KeyImportPanel
                authenticated
                canMutate={false}
                onUnauthorized={() => false}
                submittedImports={[]}
                onImportCompleted={vi.fn()}
            />,
        );

        await screen.findByRole('button', { name: 'Retry 1' });
        expect((screen.getByLabelText('Key file') as HTMLInputElement).disabled).toBe(true);
        expect((screen.getByRole('button', { name: 'Retry 1' }) as HTMLButtonElement).disabled).toBe(true);
        expect(screen.getByText('Completed with errors')).toBeTruthy();
    });
});
