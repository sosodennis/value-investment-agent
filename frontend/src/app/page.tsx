'use client';

import { useState, useRef, useEffect, useMemo } from 'react';
import { useAgent } from '../hooks/useAgent';
import { HeaderBar } from '../components/HeaderBar';
import { AgentsRoster } from '../components/AgentsRoster';
import { AgentDetailPanel } from '../components/AgentDetailPanel';
import { AgentInfo, AgentStatus } from '../types/agents';

export default function Home({ assistantId = "agent" }: { assistantId?: string }) {
  const {
    messages,
    sendMessage,
    submitCommand,
    loadHistory,
    isLoading,
    threadId,
    resolvedTicker,
    agentStatuses,
    financialReports,
    currentNode,
    currentStatus,
    activityFeed,
    agentOutputs
  } = useAgent(assistantId);

  const [ticker, setTicker] = useState('');
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  // Sync ticker state with resolvedTicker from hook
  useEffect(() => {
    if (resolvedTicker && !ticker) {
      setTicker(resolvedTicker);
    }
  }, [resolvedTicker, ticker]);

  // Load history only once on mount
  const hasLoadedRef = useRef(false);
  useEffect(() => {
    if (hasLoadedRef.current) return;
    hasLoadedRef.current = true;
    const savedThreadId = localStorage.getItem('agent_thread_id');
    if (savedThreadId) {
      loadHistory(savedThreadId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Save threadId
  useEffect(() => {
    if (threadId) {
      localStorage.setItem('agent_thread_id', threadId);
    }
  }, [threadId]);

  // Define Agents Roster Data (Linking to current workflow nodes)
  const agents: AgentInfo[] = useMemo(() => [
    {
      id: 'planner',
      name: 'Intent Planner',
      role: 'Strategy & Goal Setting',
      description: 'Analyzes user intent and fetches preliminary data.',
      avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Felix',
      status: agentStatuses.planner,
    },
    {
      id: 'executor',
      name: 'Data Executor',
      role: 'Market Data Retrieval',
      description: 'Executes tools to fetch real-time financial data.',
      avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Aneka',
      status: agentStatuses.executor,
    },
    {
      id: 'auditor',
      name: 'Risk Auditor',
      role: 'Compliance & Validation',
      description: 'Audits data integrity and checks for anomalies.',
      avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Liam',
      status: agentStatuses.auditor,
    },
    {
      id: 'approval',
      name: 'Chief Auditor',
      role: 'Final Decision Authority',
      description: 'Manages human-in-the-loop approvals.',
      avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Sasha',
      status: agentStatuses.approval,
    },
    {
      id: 'calculator',
      name: 'Valuation Engine',
      role: 'DCF & Model Execution',
      description: 'Performs finalized financial calculations.',
      avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Coco',
      status: agentStatuses.calculator,
    },
  ], [agentStatuses]);

  const handleStartAnalysis = () => {
    if (!ticker || isLoading) return;
    sendMessage(`Valuate ${ticker}`);
  };

  const selectedAgent = agents.find(a => a.id === selectedAgentId) || null;
  const selectedAgentOutput = selectedAgentId ? agentOutputs[selectedAgentId] : null;

  return (
    <main className="flex flex-col h-screen w-full bg-slate-950 overflow-hidden font-sans selection:bg-cyan-500/30">
      {/* ... HeaderBar ... */}
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

      {/* Main Layout Body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left Sidebar: Agents Roster */}
        <AgentsRoster
          agents={agents}
          selectedAgentId={selectedAgentId}
          onAgentSelect={setSelectedAgentId}
        />

        {/* Main Workspace Area */}
        <div className="flex-1 flex flex-col relative">
          {/* Glass background decorative elements */}
          <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-cyan-600/5 rounded-full blur-[120px] pointer-events-none" />
          <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-emerald-600/5 rounded-full blur-[120px] pointer-events-none" />

          {/* Scrolling content or Scoped Panel */}
          <AgentDetailPanel
            agent={selectedAgent}
            agentOutput={selectedAgentOutput}
            messages={messages}
            onSubmitCommand={submitCommand}
            financialReports={financialReports}
            resolvedTicker={resolvedTicker}
            currentNode={currentNode}
            currentStatus={currentStatus}
            activityFeed={activityFeed}
          />
        </div>
      </div>

      {/* Global Status Footer */}
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
