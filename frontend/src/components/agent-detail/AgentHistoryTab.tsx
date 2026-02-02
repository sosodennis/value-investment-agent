import React from 'react';
import { MessageSquare, BarChart3 } from 'lucide-react';
import { Message } from '@/types/protocol';
import { DynamicInterruptForm } from '../DynamicInterruptForm';

interface AgentHistoryTabProps {
    agentMessages: Message[];
    onSubmitCommand?: (payload: any) => Promise<void>;
}

export const AgentHistoryTab: React.FC<AgentHistoryTabProps> = ({
    agentMessages,
    onSubmitCommand
}) => {
    return (
        <div className="flex flex-col h-full animate-in slide-in-from-bottom-2 duration-300">
            {agentMessages.length === 0 ? (
                <div className="flex-1 flex flex-col items-center justify-center p-12 text-center">
                    <MessageSquare size={48} className="text-slate-900 mb-4" />
                    <h4 className="text-label">No activity yet</h4>
                    <p className="text-slate-700 text-[10px] mt-2 max-w-[200px]">This agent has not generated any messages or outputs for this session yet.</p>
                </div>
            ) : (
                <div className="p-8 space-y-6">
                    {agentMessages.map((msg, i) => (
                        <div key={msg.id || i} className={`group flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                            <div className={`max-w-[85%] rounded-2xl p-4 text-sm leading-relaxed border ${msg.role === 'user' ? 'bg-primary/10 border-primary/20 text-slate-100' : 'bg-bg-main/40 border-border-subtle text-slate-300'}`}>
                                {msg.content}

                                {/* Financial Report View */}
                                {msg.type === 'financial_report' && (
                                    <div className="mt-4 p-4 bg-bg-main/50 rounded-xl border border-border-main">
                                        <div className="flex items-center gap-2 mb-3 text-primary">
                                            <BarChart3 size={14} />
                                            <span className="text-label text-primary">Extracted Financials</span>
                                        </div>
                                        <div className="text-[10px] text-slate-400 italic">
                                            Detailed financial metrics successfully extracted from SEC EDGAR. Switch to the &quot;Score&quot; tab for the full analysis.
                                        </div>
                                    </div>
                                )}

                                {/* Dynamic Interrupt Forms (SDUI) */}
                                {msg.isInteractive && msg.data?.schema && (
                                    <div className="mt-6">
                                        <DynamicInterruptForm
                                            schema={msg.data.schema}
                                            uiSchema={msg.data.ui_schema}
                                            title={msg.data.title}
                                            description={msg.data.description}
                                            onSubmit={(data) => onSubmitCommand?.(data)}
                                        />
                                    </div>
                                )}

                                {msg.isInteractive && !msg.type?.startsWith('interrupt') && (
                                    <div className="mt-4 pt-4 border-t border-border-main flex gap-2">
                                        <span className="text-[10px] font-bold text-warning uppercase tracking-widest animate-pulse">Waiting for action...</span>
                                    </div>
                                )}
                            </div>
                            <span className="mt-2 px-2 text-[9px] font-bold text-slate-700 uppercase tracking-widest">{msg.role}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};
