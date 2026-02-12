'use client';

import { useState, useRef, useEffect, useMemo } from 'react';
import { useAgent } from '../hooks/useAgent';
import { useFinancialData } from '../hooks/useFinancialData';
import { HeaderBar } from '../components/HeaderBar';
import { AgentsRoster } from '../components/AgentsRoster';
import { AgentDetailPanel } from '../components/AgentDetailPanel';
import { AgentInfo } from '@/types/agents';
import { AGENT_CONFIGS } from '../config/agents';

export default function Home({ assistantId = "agent" }: { assistantId?: string }) {
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
    activityFeed,
    agentOutputs
  } = useAgent(assistantId);

  const [ticker, setTicker] = useState('');
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

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

  // Load history only once on mount
  const hasLoadedRef = useRef(false);
  useEffect(() => {
    if (hasLoadedRef.current) return;
    hasLoadedRef.current = true;

    // Explicitly safe access to localStorage inside useEffect
    if (typeof window !== 'undefined') {
      const savedThreadId = localStorage.getItem('agent_thread_id');
      if (savedThreadId) {
        loadHistory(savedThreadId);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Save threadId
  useEffect(() => {
    if (threadId && typeof window !== 'undefined') {
      localStorage.setItem('agent_thread_id', threadId);
    }
  }, [threadId]);

  // Define Agents Roster Data (Linking to current workflow nodes)
  // Derive 'attention' status from active interrupts
  const hasTickerInterrupt = messages.some(m => m.isInteractive && (m.type === 'interrupt_ticker' || m.agentId === 'intent_extraction'));

  const agents: AgentInfo[] = useMemo(() => {
    return AGENT_CONFIGS.map((config: any) => {
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

  const handleStartAnalysis = () => {
    if (!ticker || isLoading) return;
    sendMessage(`Valuate ${ticker}`, true);
  };

  const selectedAgent = agents.find(a => a.id === selectedAgentId) || null;
  const selectedAgentOutput = selectedAgentId ? agentOutputs[selectedAgentId] : null;

  return (
    <main className="flex flex-col h-screen w-full bg-slate-950 overflow-hidden font-sans selection:bg-cyan-500/30">
      <HeaderBar
        systemStatus="online"
        activeAgents={agents.filter(a => a.status !== 'idle').length}
        stage={isLoading ? 'Running' : 'Idle'}
        ticker={ticker}
        onTickerChange={setTicker}
        onStartAnalysis={handleStartAnalysis}
        onShowHistory={() => { }}
        isLoading={isLoading}
      />

      <div className="flex flex-1 overflow-hidden">
        <AgentsRoster
          agents={agents}
          selectedAgentId={selectedAgentId}
          onAgentSelect={setSelectedAgentId}
        />

        <div className="flex-1 flex flex-col relative">
          <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-cyan-600/5 rounded-full blur-[120px] pointer-events-none" />
          <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-emerald-600/5 rounded-full blur-[120px] pointer-events-none" />

          <AgentDetailPanel
            agent={selectedAgent}
            agentOutput={selectedAgentOutput}
            messages={messages}
            onSubmitCommand={submitCommand}
            allAgentOutputs={agentOutputs}
            currentNode={currentNode}
            currentStatus={globalStatus}
            activityFeed={activityFeed}
          />
        </div>
      </div>

      <footer className="h-8 w-full bg-slate-900/50 border-t border-slate-900 px-8 flex items-center justify-between z-10">
        <div className="flex items-center gap-4">
          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">
            Neuro-Symbolic Engine v2.4
          </span>
          <div className="w-1 h-1 bg-slate-800 rounded-full" />
          <span className="text-[10px] font-medium text-slate-600">
            Powered by LangGraph Checkpointer
          </span>
        </div>

        {threadId && (
          <div className="flex items-center gap-2">
            <span className="text-[9px] font-mono text-slate-500">SESSION: {threadId.slice(-12)}</span>
          </div>
        )}
      </footer>
    </main>
  );
}
