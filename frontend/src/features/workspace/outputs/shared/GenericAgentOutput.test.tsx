import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { GenericAgentOutput } from './GenericAgentOutput';

const mockUseArtifact = vi.fn();

vi.mock('../../../../hooks/useArtifact', () => ({
    useArtifact: (...args: unknown[]) => mockUseArtifact(...args),
}));

describe('GenericAgentOutput', () => {
    beforeEach(() => {
        mockUseArtifact.mockReturnValue({
            data: { result: 'full report' },
            isLoading: false,
            error: null,
            retry: vi.fn(),
            isRetrying: false,
            retryable: false,
        });
    });

    it('preserves the run-scoped artifact reference', () => {
        const reference = {
            artifact_id: 'generic-report',
            download_url: '/api/v1/artifacts/generic-report?run_id=run-generic-1',
            type: 'generic.output',
        };

        render(
            <GenericAgentOutput
                agentName="Generic agent"
                viewModel={{
                    kind: 'generic',
                    agentId: 'generic',
                    summary: null,
                    preview: null,
                    reference,
                    errorLogs: [],
                    outputKind: 'generic.output',
                }}
                status="done"
            />
        );

        expect(mockUseArtifact).toHaveBeenCalledWith(
            reference,
            expect.any(Function),
            'generic_output.artifact'
        );
        screen.getByText('Generic agent result');
        screen.getByText(/full report/);
    });
});
