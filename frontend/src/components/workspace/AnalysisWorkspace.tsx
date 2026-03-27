'use client';

import { useState, useRef, useEffect, useMemo } from 'react';
import { useAgent } from '@/hooks/useAgent';
import { useFinancialData } from '@/hooks/useFinancialData';
import { WorkspaceLayout } from '@/components/workspace/layout';
import { AgentsRoster } from '@/components/workspace/agents-roster/AgentsRoster';
import { AgentDetailPanel } from '@/components/workspace/agent-detail/AgentDetailPanel';
import { AgentInfo } from '@/types/agents';
import { AGENT_CONFIGS, AgentConfig } from '@/config/agents';

type AnalysisWorkspaceProps = {
    assistantId?: string;
    initialTicker?: string | null;
    autoStart?: boolean;
};

export function AnalysisWorkspace({
    assistantId = 'agent',
    initialTicker = null,
    autoStart = false,
}: AnalysisWorkspaceProps) {
    const {
        messages,
        sendMessage,
        submitCommand,
        loadHistory,
        isLoading,
        threadId,
        agentStatuses,
        currentNode,
        currentStatus: globalStatus,
        agentOutputs,
        activeAgentId,
        projectionUpdatedAt,
    } = useAgent(assistantId);

    const [ticker, setTicker] = useState(
        initialTicker ? initialTicker.toUpperCase() : ''
    );
    const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
    const syncedSelectionThreadIdRef = useRef<string | null>(null);
    const hasAutoStartedRef = useRef(false);
    const hasAppliedInitialTickerRef = useRef(false);

    // Hook 1: Extract Ticker & Financial Logic
    // We use 'intent_extraction' as the primary source for the ticker.
    // We could pass selectedAgentId if we wanted agent-specific financial contexts,
    // but for the global ticker, intent extraction is the source of truth.
    const { resolvedTicker } = useFinancialData('intent_extraction', agentOutputs);
    const lastResolvedTickerRef = useRef<string | null>(null);

    useEffect(() => {
        if (resolvedTicker && resolvedTicker !== lastResolvedTickerRef.current) {
            setTicker(resolvedTicker);
            lastResolvedTickerRef.current = resolvedTicker;
        } else if (!resolvedTicker) {
            lastResolvedTickerRef.current = null;
        }
    }, [resolvedTicker]);

    useEffect(() => {
        if (hasAppliedInitialTickerRef.current) return;
        if (!initialTicker) return;
        setTicker(initialTicker.toUpperCase());
        hasAppliedInitialTickerRef.current = true;
    }, [initialTicker]);

    const allowHistoryRestore = !autoStart && !initialTicker;

    // Load history only once on mount (when allowed)
    const hasLoadedRef = useRef(false);
    useEffect(() => {
        if (!allowHistoryRestore) return;
        if (hasLoadedRef.current) return;
        hasLoadedRef.current = true;

        // Explicitly safe access to localStorage inside useEffect
        if (typeof window !== 'undefined') {
            const savedThreadId = localStorage.getItem('agent_thread_id');
            const savedSelectedAgentId = localStorage.getItem(
                'agent_selected_agent_id'
            );
            if (savedSelectedAgentId) {
                setSelectedAgentId(savedSelectedAgentId);
            }
            if (savedThreadId) {
                loadHistory(savedThreadId);
            }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [allowHistoryRestore]);

    // Save threadId
    useEffect(() => {
        if (threadId && typeof window !== 'undefined') {
            localStorage.setItem('agent_thread_id', threadId);
        }
    }, [threadId]);

    useEffect(() => {
        if (selectedAgentId && typeof window !== 'undefined') {
            localStorage.setItem('agent_selected_agent_id', selectedAgentId);
        }
    }, [selectedAgentId]);

    useEffect(() => {
        if (!threadId || !activeAgentId) {
            return;
        }
        if (syncedSelectionThreadIdRef.current === threadId) {
            return;
        }
        setSelectedAgentId(activeAgentId);
        syncedSelectionThreadIdRef.current = threadId;
    }, [threadId, activeAgentId]);

    // Define Agents Roster Data (Linking to current workflow nodes)
    // Derive 'attention' status from active interrupts
    const hasTickerInterrupt = messages.some(
        (m) => m.isInteractive && m.type === 'interrupt.request'
    );

    const agents: AgentInfo[] = useMemo(() => {
        return AGENT_CONFIGS.map((config: AgentConfig) => {
            const baseStatus = agentStatuses[config.id] || 'idle';
            return {
                id: config.id,
                name: config.name,
                role: config.role,
                description: config.description,
                avatar: config.avatar,
                status: config.getStatus
                    ? config.getStatus(baseStatus, hasTickerInterrupt)
                    : baseStatus,
            };
        });
    }, [agentStatuses, hasTickerInterrupt]);

    useEffect(() => {
        if (selectedAgentId) {
            return;
        }
        const preferredAgent =
            agents.find((agent) => agent.status === 'running' || agent.status === 'attention') ||
            agents.find((agent) => agent.status !== 'idle');
        if (preferredAgent) {
            setSelectedAgentId(preferredAgent.id);
        }
    }, [agents, selectedAgentId]);

    useEffect(() => {
        if (!autoStart || hasAutoStartedRef.current) return;
        const candidate = (initialTicker || ticker).trim().toUpperCase();
        if (!candidate || isLoading) return;
        hasAutoStartedRef.current = true;
        if (candidate !== ticker) {
            setTicker(candidate);
        }
        sendMessage(`Valuate ${candidate}`, true);
    }, [autoStart, initialTicker, ticker, isLoading, sendMessage]);

    const selectedAgent = agents.find((a) => a.id === selectedAgentId) || null;
    const selectedAgentOutput = selectedAgentId
        ? agentOutputs[selectedAgentId]
        : null;

    return (
        <WorkspaceLayout.Root>
            <WorkspaceLayout.Main>
                <WorkspaceLayout.Sidebar className="w-80">
                    <AgentsRoster
                        agents={agents}
                        selectedAgentId={selectedAgentId}
                        onAgentSelect={setSelectedAgentId}
                        systemStatus="online"
                        stage={isLoading ? 'Running' : 'Idle'}
                        targetTicker={ticker}
                    />
                </WorkspaceLayout.Sidebar>

                <WorkspaceLayout.Content>
                    <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-primary/5 rounded-full blur-[120px] pointer-events-none" />
                    <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-secondary/5 rounded-full blur-[120px] pointer-events-none" />

                    <AgentDetailPanel
                        agent={selectedAgent}
                        agentOutput={selectedAgentOutput}
                        messages={messages}
                        onSubmitCommand={submitCommand}
                        allAgentOutputs={agentOutputs}
                        currentNode={currentNode}
                        currentStatus={globalStatus}
                        threadId={threadId}
                        projectionUpdatedAt={projectionUpdatedAt}
                    />
                </WorkspaceLayout.Content>
            </WorkspaceLayout.Main>

            <WorkspaceLayout.Footer>
                <div className="flex items-center gap-4">
                    <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">
                        Neuro-Symbolic Engine v2.4
                    </span>
                    <div className="w-1 h-1 bg-outline-variant rounded-full" />
                    <span className="text-[10px] font-medium text-outline">
                        Powered by LangGraph Checkpointer
                    </span>
                </div>

                {threadId && (
                    <div className="flex items-center gap-2">
                        <span className="text-[9px] font-mono text-outline">
                            SESSION: {threadId.slice(-12)}
                        </span>
                    </div>
                )}
            </WorkspaceLayout.Footer>
        </WorkspaceLayout.Root>
    );
}
