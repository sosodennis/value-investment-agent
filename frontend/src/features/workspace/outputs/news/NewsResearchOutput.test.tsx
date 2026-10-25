import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { NewsResearchOutput } from './NewsResearchOutput';

const mockUseArtifact = vi.fn();

vi.mock('../../../../hooks/useArtifact', () => ({
    useArtifact: (...args: unknown[]) => mockUseArtifact(...args),
}));

describe('NewsResearchOutput', () => {
    beforeEach(() => {
        mockUseArtifact.mockReturnValue({ data: null, isLoading: false, error: null });
    });

    it('shows an error state when a completed run cannot load its report artifact', () => {
        mockUseArtifact.mockReturnValue({
            data: null,
            isLoading: false,
            error: new Error('News artifact request failed.'),
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
        expect(screen.queryByText(/scanning global financial news/i)).toBeNull();
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
