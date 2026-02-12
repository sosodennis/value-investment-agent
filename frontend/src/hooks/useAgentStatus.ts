import { useMemo } from 'react';
import { AgentStatus } from '@/types/agents';
import { Message } from '@/types/protocol';

export const useAgentStatus = (
    agentId: string,
    baseStatus: AgentStatus,
    messages: Message[]
): AgentStatus => {
    return useMemo(() => {
        // 1. Check for Ticker Interrupt (Intent Planner)
        if (agentId === 'intent_extraction') {
            const hasTickerInterrupt = messages.some(m =>
                m.isInteractive &&
                m.type === 'interrupt.request' &&
                m.agentId === 'intent_extraction'
            );
            if (hasTickerInterrupt) return 'attention';
        }

        // 2. Default (or other custom logic per agent)
        return baseStatus;
    }, [agentId, baseStatus, messages]);
};
