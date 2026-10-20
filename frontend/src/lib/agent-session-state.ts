import type { AgentStatus } from '@/types/agents';
import type { StatusHistoryEntry, ThreadStateResponse } from '@/types/protocol';

type AgentSessionSnapshot = Partial<
    Pick<ThreadStateResponse, 'agent_statuses' | 'node_statuses'>
> & {
    active_agent_id?: string | null;
    current_node?: string | null;
    current_status?: AgentStatus | null;
    status_history?: StatusHistoryEntry[];
    is_running?: boolean;
};

export const isLiveAgentStatus = (status: AgentStatus): boolean =>
    status === 'running' || status === 'attention';

export const deriveActiveAgentId = (
    snapshot: AgentSessionSnapshot
): string | null => {
    if (snapshot.active_agent_id) return snapshot.active_agent_id;

    const lastLiveEntry = [...(snapshot.status_history ?? [])]
        .reverse()
        .find((entry) => isLiveAgentStatus(entry.status));
    if (lastLiveEntry) return lastLiveEntry.agentId;

    if (
        snapshot.current_node &&
        snapshot.current_status &&
        isLiveAgentStatus(snapshot.current_status)
    ) {
        return snapshot.current_node;
    }

    if (snapshot.is_running) {
        const runningAgent = Object.entries(snapshot.agent_statuses ?? {}).find(
            ([, status]) => isLiveAgentStatus(status)
        );
        if (runningAgent) return runningAgent[0];
    }

    return null;
};

export const deriveHydratedAgentStatuses = (
    snapshot: Pick<ThreadStateResponse, 'agent_statuses' | 'node_statuses'>
): Record<string, AgentStatus> => ({
    ...snapshot.node_statuses,
    ...snapshot.agent_statuses,
});
