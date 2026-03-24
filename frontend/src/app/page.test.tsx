'use client';

import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AnalysisWorkspace } from '@/components/workspace/AnalysisWorkspace';
import { useAgent } from '@/hooks/useAgent';
import { useFinancialData } from '@/hooks/useFinancialData';

vi.mock('@/hooks/useAgent', () => ({
    useAgent: vi.fn(),
}));

vi.mock('@/hooks/useFinancialData', () => ({
    useFinancialData: vi.fn(),
}));

vi.mock('@/components/HeaderBar', () => ({
    HeaderBar: () => <div data-testid="header-bar" />,
}));

vi.mock('@/components/AgentsRoster', () => ({
    AgentsRoster: ({
        selectedAgentId,
    }: {
        selectedAgentId: string | null;
    }) => <div data-testid="agents-roster">{selectedAgentId ?? 'none'}</div>,
}));

vi.mock('@/components/AgentDetailPanel', () => ({
    AgentDetailPanel: ({
        agent,
    }: {
        agent: { id: string } | null;
    }) => <div data-testid="agent-detail">{agent?.id ?? 'none'}</div>,
}));

const mockUseAgent = vi.mocked(useAgent);
const mockUseFinancialData = vi.mocked(useFinancialData);
const storage = new Map<string, string>();

describe('AnalysisWorkspace refresh restore behavior', () => {
    beforeEach(() => {
        storage.clear();
        vi.stubGlobal('localStorage', {
            getItem: (key: string) => storage.get(key) ?? null,
            setItem: (key: string, value: string) => {
                storage.set(key, value);
            },
            removeItem: (key: string) => {
                storage.delete(key);
            },
            clear: () => {
                storage.clear();
            },
        });
        mockUseFinancialData.mockReturnValue({
            resolvedTicker: null,
            dimensionScores: [],
            financialMetrics: [],
            latestReport: null,
            rawOutput: null,
        });
    });

    it('focuses the active agent after refresh even if localStorage points to a stale selection', async () => {
        localStorage.setItem('agent_thread_id', 'thread_1');
        localStorage.setItem('agent_selected_agent_id', 'technical_analysis');

        mockUseAgent.mockReturnValue({
            messages: [],
            sendMessage: vi.fn(),
            submitCommand: vi.fn(),
            loadHistory: vi.fn(),
            isLoading: false,
            error: null,
            threadId: 'thread_1',
            hasMore: true,
            agentStatuses: {
                intent_extraction: 'done',
                technical_analysis: 'done',
                financial_news_research: 'running',
            },
            agentOutputs: {},
            currentNode: 'semantic_translate',
            currentStatus: 'running',
            activityFeed: [
                {
                    id: 'status_1',
                    node: 'financial_news_research',
                    agentId: 'financial_news_research',
                    status: 'running',
                    timestamp: Date.parse('2026-03-21T08:00:00Z'),
                },
            ],
            activeAgentId: 'financial_news_research',
        });

        render(<AnalysisWorkspace />);

        await waitFor(() => {
            expect(screen.getByTestId('agent-detail').textContent).toBe(
                'financial_news_research'
            );
        });
    });
});
