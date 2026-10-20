import { describe, expect, it } from 'vitest';
import {
    deriveActiveAgentId,
    deriveHydratedAgentStatuses,
    isLiveAgentStatus,
} from './agent-session-state';

describe('agent session state', () => {
    it('prefers the explicit active agent and otherwise uses latest live history', () => {
        const status_history = [
            {
                id: 'status_1',
                node: 'intent_extraction',
                agentId: 'intent_extraction',
                status: 'running' as const,
                timestamp: 1,
            },
            {
                id: 'status_2',
                node: 'financial_news_research',
                agentId: 'financial_news_research',
                status: 'attention' as const,
                timestamp: 2,
            },
        ];

        expect(
            deriveActiveAgentId({
                active_agent_id: 'debate',
                status_history,
                agent_statuses: {},
                node_statuses: {},
            })
        ).toBe('debate');
        expect(
            deriveActiveAgentId({
                status_history,
                agent_statuses: {},
                node_statuses: {},
            })
        ).toBe('financial_news_research');
    });

    it('hydrates agent-level values over node values and identifies live statuses', () => {
        expect(
            deriveHydratedAgentStatuses({
                node_statuses: {
                    intent_extraction: 'idle',
                    fundamental_analysis: 'running',
                },
                agent_statuses: {
                    intent_extraction: 'done',
                },
            })
        ).toEqual({
            intent_extraction: 'done',
            fundamental_analysis: 'running',
        });
        expect(isLiveAgentStatus('running')).toBe(true);
        expect(isLiveAgentStatus('attention')).toBe(true);
        expect(isLiveAgentStatus('done')).toBe(false);
    });
});
