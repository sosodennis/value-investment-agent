import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { NewsResearchOutput } from './NewsResearchOutput';

const mockUseArtifact = vi.fn();
const mockRetry = vi.fn();

vi.mock('../../../../hooks/useArtifact', () => ({
    useArtifact: (...args: unknown[]) => mockUseArtifact(...args),
}));

describe('NewsResearchOutput', () => {
    beforeEach(() => {
        mockRetry.mockReset();
        mockUseArtifact.mockReturnValue({
            data: null,
            isLoading: false,
            error: null,
            retry: mockRetry,
            isRetrying: false,
            retryable: false,
        });
    });

    it('shows an error state when a completed run cannot load its report artifact', () => {
        mockUseArtifact.mockReturnValue({
            data: null,
            isLoading: false,
            error: new Error('News artifact request failed.'),
            retry: mockRetry,
            isRetrying: false,
            retryable: false,
        });

        render(
            <NewsResearchOutput
                reference={{
                    artifact_id: 'news-failed',
                    download_url: '/api/v1/artifacts/news-failed',
                    type: 'application/json',
                }}
                previewData={null}
                resolvedTicker="AAPL"
                status="done"
            />
        );

        screen.getByRole('alert');
        screen.getByText('News report unavailable');
        screen.getByText('News artifact request failed.');
        expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull();
        expect(screen.queryByText(/scanning global financial news/i)).toBeNull();
    });

    it('exposes an artifact-scoped retry action for a recoverable report failure', () => {
        mockUseArtifact.mockReturnValue({
            data: null,
            isLoading: false,
            error: new Error('The artifact service is temporarily unavailable.'),
            retry: mockRetry,
            isRetrying: false,
            retryable: true,
        });

        render(
            <NewsResearchOutput
                reference={{
                    artifact_id: 'news-retry',
                    download_url: '/api/v1/artifacts/news-retry',
                    type: 'application/json',
                }}
                previewData={null}
                resolvedTicker="AAPL"
                status="done"
            />
        );

        fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
        expect(mockRetry).toHaveBeenCalledOnce();
    });

    it('shows an empty state when a completed run has no report or preview', () => {
        render(
            <NewsResearchOutput
                reference={null}
                previewData={null}
                resolvedTicker="AAPL"
                status="done"
            />
        );

        screen.getByText('No news research available');
    });
});
