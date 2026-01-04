'use client';

import { useState, useRef, useEffect } from 'react';
import { useAgent, Message } from '../hooks/useAgent';
import { Bot, User, Send, TrendingUp, CheckCircle2, AlertCircle, List } from 'lucide-react';
import { FinancialTable } from '../components/FinancialTable';

// --- Sub-components for Unified Messaging ---

function InterruptTickerUI({ data, onSelect, isInteractive }: { data: any, onSelect: (t: string) => void, isInteractive?: boolean }) {
  if (!data) return null;
  return (
    <div className="max-w-[80%] bg-slate-900 border-2 border-indigo-500/50 p-5 rounded-2xl rounded-tl-none shadow-2xl shadow-indigo-500/10">
      <div className="space-y-4">
        <div className="flex items-center gap-2 text-indigo-400">
          <List size={18} />
          <h3 className="font-bold text-sm">Select Ticker</h3>
        </div>
        <p className="text-xs text-slate-400">Multiple tickers found. Please select one:</p>
        <div className="grid grid-cols-1 gap-2">
          {data.candidates?.map((c: any) => (
            <button
              key={c.symbol}
              onClick={() => isInteractive && onSelect(c.symbol)}
              disabled={!isInteractive}
              className={`flex items-center justify-between p-3 border rounded-xl transition-all group ${isInteractive
                ? 'bg-slate-800 hover:bg-slate-700 border-slate-700 cursor-pointer'
                : 'bg-slate-900/50 border-slate-800 opacity-50 cursor-not-allowed'
                }`}
            >
              <div className="text-left">
                <span className="font-bold text-sm block">{c.symbol}</span>
                <span className="text-[10px] text-slate-500 block line-clamp-1">{c.name} ({c.exchange})</span>
              </div>
              <TrendingUp size={14} className="text-slate-600" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function InterruptApprovalUI({ data, onApprove, isInteractive }: { data: any, onApprove: (v: boolean) => void, isInteractive?: boolean }) {
  if (!data) return null;
  return (
    <div className="max-w-[80%] bg-slate-900 border-2 border-emerald-500/50 p-5 rounded-2xl rounded-tl-none shadow-2xl shadow-emerald-500/10">
      <div className="space-y-4">
        <div className="flex items-center gap-2 text-emerald-400">
          <CheckCircle2 size={18} />
          <h3 className="font-bold text-sm">Audit Confirmation</h3>
        </div>
        <div className="bg-slate-950 p-3 rounded-xl border border-slate-800 space-y-2">
          <div className="flex justify-between text-xs">
            <span className="text-slate-500 uppercase tracking-tighter font-bold">Ticker</span>
            <span className="text-slate-200 font-bold">{data.details?.ticker}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-slate-500 uppercase tracking-tighter font-bold">Model</span>
            <span className="text-slate-200">{data.details?.model}</span>
          </div>
          <div className="pt-2 mt-2 border-t border-slate-800">
            <p className="text-[10px] text-slate-500 italic">
              {isInteractive ? "Ready to execute terminal calculation?" : "Audit decision recorded."}
            </p>
          </div>
        </div>
        {isInteractive && (
          <div className="flex gap-2">
            <button
              onClick={() => onApprove(true)}
              className="flex-1 px-4 py-2.5 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 rounded-xl text-xs font-bold transition-all shadow-lg text-white"
            >
              Approve & Run
            </button>
            <button
              onClick={() => onApprove(false)}
              className="px-4 py-2.5 bg-slate-800 hover:bg-red-900/40 border border-slate-700 rounded-xl text-xs font-medium transition-all text-white"
            >
              Reject
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export interface DashboardProps {
  assistantId?: string;
}

export default function Home({ assistantId = "agent" }: DashboardProps) {
  const { messages, sendMessage, submitCommand, isLoading, threadId, resolvedTicker } = useAgent(assistantId);
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Debug render state
  console.log("🎨 Render - isLoading:", isLoading, "Msgs:", messages.length);

  // Auto-scroll to bottom
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setInput(e.target.value);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;
    sendMessage(input);
    setInput('');
  };

  const handleApprove = (approved: boolean) => {
    if (isLoading) return;
    console.log("👆 handleApprove clicked:", approved);
    submitCommand({ approved });
  };

  const handleSelectTicker = (ticker: string) => {
    if (isLoading) return;
    submitCommand({ selected_symbol: ticker });
  };

  return (
    <main className="flex min-h-screen flex-col items-center bg-slate-950 text-slate-50 font-sans">
      {/* Header */}
      <header className="w-full max-w-4xl py-8 px-4 flex items-center justify-between border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className="bg-indigo-600 p-2 rounded-lg shadow-lg shadow-indigo-500/20">
            <TrendingUp size={24} className="text-white" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-cyan-400">
            FinGraph <span className="text-slate-500 font-medium text-lg ml-2">Valuation Engine</span>
          </h1>
        </div>
        {threadId && (
          <div className="text-[10px] text-slate-500 font-mono bg-slate-900 px-2 py-1 rounded border border-slate-800">
            ID: {threadId.slice(-8)}
          </div>
        )}
      </header>

      {/* Chat Area */}
      <section className="flex-1 w-full max-w-4xl overflow-y-auto px-4 py-8 space-y-6 scrollbar-hide">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center space-y-4 pt-20">
            <div className="bg-slate-900 border border-slate-800 p-8 rounded-2xl max-w-md shadow-xl">
              <h2 className="text-xl font-semibold mb-2">Welcome to your Agentic Auditor</h2>
              <p className="text-slate-400 text-sm">
                Ask me to valuate any stock. I'll analyze financial reports, apply valuation models, and guide you through the audit process.
              </p>
              <div className="mt-6 flex flex-wrap gap-2 justify-center">
                {['Value Tesla', 'NVIDIA Valuation', 'Google DCF'].map(suggestion => (
                  <button
                    key={suggestion}
                    onClick={() => { setInput(suggestion); }}
                    className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-full text-xs transition-colors"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          messages.map((m) => {
            // 1. Render Financial Table Message
            if (m.type === 'financial_report') {
              return (
                <div key={m.id} className="flex gap-4 justify-start animate-in fade-in slide-in-from-bottom-2">
                  <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center shrink-0">
                    <Bot size={18} />
                  </div>
                  <div className="w-full max-w-[90%]">
                    <FinancialTable reports={m.data} ticker={resolvedTicker || 'Unknown'} />
                  </div>
                </div>
              );
            }

            // 2. Render Interrupts (Ticker Selection)
            if (m.type === 'interrupt_ticker') {
              return (
                <div key={m.id} className="flex gap-4 justify-start animate-in fade-in slide-in-from-bottom-2">
                  <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center shrink-0">
                    <AlertCircle size={18} />
                  </div>
                  <InterruptTickerUI
                    data={m.data}
                    onSelect={handleSelectTicker}
                    isInteractive={m.isInteractive}
                  />
                </div>
              );
            }

            // 3. Render Interrupts (Approval)
            if (m.type === 'interrupt_approval') {
              return (
                <div key={m.id} className="flex gap-4 justify-start animate-in fade-in slide-in-from-bottom-2">
                  <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center shrink-0">
                    <AlertCircle size={18} />
                  </div>
                  <InterruptApprovalUI
                    data={m.data}
                    onApprove={handleApprove}
                    isInteractive={m.isInteractive}
                  />
                </div>
              );
            }

            // 4. Default Text Message (User or Bot)
            return (
              <div
                key={m.id}
                className={`flex gap-4 ${m.role === 'user' ? 'justify-end' : 'justify-start'} animate-in fade-in slide-in-from-bottom-2`}
              >
                {m.role !== 'user' && (
                  <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center shrink-0">
                    <Bot size={18} />
                  </div>
                )}

                <div className={`max-w-[80%] px-4 py-3 rounded-2xl ${m.role === 'user'
                  ? 'bg-indigo-600 text-white rounded-tr-none shadow-lg shadow-indigo-500/10'
                  : 'bg-slate-900 border border-slate-800 rounded-tl-none'
                  }`}>
                  <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-200">
                    {m.content}
                  </div>
                </div>

                {m.role === 'user' && (
                  <div className="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center shrink-0">
                    <User size={18} />
                  </div>
                )}
              </div>
            )
          })
        )}

        {isLoading && (
          <div className="flex gap-4">
            <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center shrink-0 animate-pulse">
              <Bot size={18} />
            </div>
            <div className="bg-slate-900 border border-slate-800 px-4 py-3 rounded-2xl rounded-tl-none">
              <div className="flex gap-1">
                <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce [animation-delay:-0.3s]"></span>
                <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce [animation-delay:-0.15s]"></span>
                <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce"></span>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </section>

      {/* Input Area */}
      <footer className="w-full max-w-4xl p-6 bg-slate-950/80 backdrop-blur-md sticky bottom-0">
        <form onSubmit={handleSubmit} className="relative group">
          <input
            className="w-full bg-slate-900 border border-slate-800 rounded-full py-4 pl-6 pr-14 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 focus:border-indigo-500 transition-all text-sm placeholder:text-slate-500 shadow-2xl"
            value={input}
            placeholder={isLoading ? "Agent is thinking..." : "Type your valuation request..."}
            onChange={handleInputChange}
          // disabled={isLoading} // Allow typing while loading for better UX
          />
          <button
            type="submit"
            disabled={isLoading || !input?.trim()}
            className="absolute right-2 top-2 bottom-2 aspect-square bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:hover:bg-indigo-600 rounded-full flex items-center justify-center transition-all"
          >
            <Send size={18} />
          </button>
        </form>
        <p className="mt-3 text-center text-slate-500 text-[10px] uppercase tracking-widest font-medium">
          Neuro-Symbolic Valuation Engine • Powered by LangGraph React SDK
        </p>
      </footer>
    </main>
  );
}
