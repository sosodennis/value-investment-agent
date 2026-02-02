import React from 'react';
import { AgentInfo, DimensionScore } from '@/types/agents';
import { BarChart3, TrendingUp, FileText } from 'lucide-react';

interface AgentScoreTabProps {
    agent: AgentInfo;
    dimensionScores: DimensionScore[];
    financialMetrics: { label: string; value: string | number }[];
    latestReport: any;
}

export const AgentScoreTab: React.FC<AgentScoreTabProps> = ({
    agent,
    dimensionScores,
    financialMetrics,
    latestReport
}) => {
    return (
        <div className="p-8 space-y-8 animate-in slide-in-from-bottom-2 duration-300">
            {/* Dimension Scores Card */}
            <section className="bg-slate-900/20 border border-slate-800/50 rounded-2xl p-8 backdrop-blur-sm">
                <div className="flex items-center gap-3 mb-8">
                    <BarChart3 size={18} className="text-cyan-400" />
                    <h3 className="text-sm font-bold text-white uppercase tracking-widest">Analysis Dimensions</h3>
                </div>

                <div className="space-y-6">
                    {dimensionScores.map((score) => (
                        <div key={score.name} className="space-y-2">
                            <div className="flex justify-between items-center text-[10px] font-bold uppercase tracking-widest">
                                <span className="text-slate-400">{score.name}</span>
                                <span className="text-white">{score.score}%</span>
                            </div>
                            <div className="h-1.5 w-full bg-slate-900 rounded-full overflow-hidden">
                                <div
                                    className={`h-full ${score.color} transition-all duration-1000 ease-out shadow-[0_0_10px_rgba(34,211,238,0.2)]`}
                                    style={{ width: `${score.score}%` }}
                                />
                            </div>
                        </div>
                    ))}
                </div>
            </section>

            {/* Financial Metrics */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <section className="bg-slate-900/20 border border-slate-800/50 rounded-2xl p-6">
                    <h3 className="text-sm font-bold text-white mb-6 flex items-center gap-2">
                        <TrendingUp size={16} className="text-cyan-400" />
                        Core Metrics
                    </h3>
                    <div className="space-y-4">
                        {financialMetrics.map(m => (
                            <div key={m.label} className="flex justify-between items-center border-b border-slate-900 pb-3">
                                <span className="text-[11px] text-slate-500 font-medium">{m.label}</span>
                                <span className="text-xs font-bold text-slate-200">{m.value}</span>
                            </div>
                        ))}
                    </div>
                </section>

                <section className="bg-slate-900/20 border border-slate-800/50 rounded-2xl p-6">
                    <h3 className="text-sm font-bold text-white mb-6 flex items-center gap-2">
                        <FileText size={16} className="text-cyan-400" />
                        Agent Context
                    </h3>
                    <div className="text-xs text-slate-400 leading-relaxed space-y-2">
                        <p>
                            {agent.description}. Current status is <span className="text-cyan-400 font-bold">{agent.status}</span>.
                        </p>
                        <p>
                            {latestReport ? (
                                `Analyzing financial data for ${latestReport.ticker || 'selected company'} showing a ROE of ${(latestReport.roe * 100).toFixed(1)}%.`
                            ) : (
                                'Waiting for financial data to be extracted and processed.'
                            )}
                        </p>
                    </div>
                </section>
            </div>
        </div>
    );
};
