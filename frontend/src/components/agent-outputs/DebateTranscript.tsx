
import React from 'react';
import ReactMarkdown from 'react-markdown';
import { TrendingUp, TrendingDown, Gavel } from 'lucide-react';

interface Message {
    name?: string;
    role?: string; // 'system' | 'human' | 'ai'
    content: string;
}

interface DebateTranscriptProps {
    history: Message[];
}

const SourceBadge = ({ source }: { source: string }) => {
    let color = "bg-slate-500/10 text-slate-400 border-slate-500/20"; // Default
    if (source.includes("Financials") || source.includes("SEC")) {
        color = "bg-emerald-500/10 text-emerald-400 border-emerald-500/20 hover:bg-emerald-500/20";
    } else if (source.includes("News")) {
        color = "bg-cyan-500/10 text-cyan-400 border-cyan-500/20 hover:bg-cyan-500/20";
    } else if (source.includes("Technicals")) {
        color = "bg-amber-500/10 text-amber-400 border-amber-500/20 hover:bg-amber-500/20";
    }

    return (
        <span className={`inline-flex items-center px-1.5 py-0.5 rounded border text-[9px] font-bold uppercase tracking-widest mx-1 cursor-default transition-colors align-middle ${color}`}>
            {source}
        </span>
    );
};

// Helper: Convert [Source: X] tags to Markdown image syntax
// This allows ReactMarkdown to parse them as images, which we then intercept
const preprocessMarkdown = (content: string) => {
    // Regex matches [Source: X] possibly wrapped in backticks
    return content.replace(/[`]?\[Source: ([^\]]+)\][`]?/g, (_, source) => {
        return `![SOURCE:${source}](badge)`;
    });
};

export const DebateTranscript: React.FC<DebateTranscriptProps> = ({ history }) => {
    if (!history || history.length === 0) return null;

    return (
        <div className="bg-slate-950/20 border border-slate-900/50 rounded-2xl overflow-hidden mt-8">
            <div className="px-6 py-4 border-b border-white/5 bg-white/5">
                <h3 className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-500 flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse"></span>
                    Intelligence Transcript
                </h3>
            </div>

            <div className="p-6 max-h-[500px] overflow-y-auto overflow-x-hidden">
                <div className="space-y-8">
                    {history.map((msg, idx) => {
                        // Filter out system messages
                        if (msg.role === 'system') return null;

                        const isBull = msg.name === 'GrowthHunter';
                        const isBear = msg.name === 'ForensicAccountant';
                        const isJudge = msg.name === 'Judge';

                        let avatarIcon = <div className="w-full h-full bg-slate-700" />;
                        let nameDisplay = msg.name || 'Agent';
                        let roleColor = "text-slate-400";
                        let ringColor = "border-slate-800";

                        if (isBull) {
                            avatarIcon = <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />;
                            roleColor = "text-emerald-400";
                            ringColor = "border-emerald-500/30";
                        } else if (isBear) {
                            avatarIcon = <TrendingDown className="w-3.5 h-3.5 text-rose-400" />;
                            roleColor = "text-rose-400";
                            ringColor = "border-rose-500/30";
                        } else if (isJudge) {
                            avatarIcon = <Gavel className="w-3.5 h-3.5 text-cyan-400" />;
                            roleColor = "text-cyan-400";
                            ringColor = "border-cyan-500/30";
                        }

                        return (
                            <div key={idx} className="flex gap-4 group">
                                <div className={`w-8 h-8 rounded-full border ${ringColor} bg-slate-900/80 flex items-center justify-center shrink-0 shadow-lg`}>
                                    {avatarIcon}
                                </div>
                                <div className="flex flex-col gap-1.5 w-full min-w-0">
                                    <div className="flex items-center gap-2">
                                        <span className={`text-[9px] font-black uppercase tracking-[0.1em] ${roleColor}`}>
                                            {nameDisplay}
                                        </span>
                                        <div className="h-px bg-white/5 flex-grow" />
                                    </div>
                                    <div className="p-4 bg-slate-900/30 rounded-xl border border-white/5 group-hover:border-white/10 group-hover:bg-slate-900/50 transition-all duration-300">
                                        <div className="text-sm leading-relaxed text-slate-300">
                                            <ReactMarkdown
                                                components={{
                                                    // Styling for standard elements
                                                    p: ({ node, ...props }) => <p className="mb-3 last:mb-0" {...props} />,
                                                    strong: ({ node, ...props }) => <strong className="font-bold text-slate-200" {...props} />,
                                                    em: ({ node, ...props }) => <em className="italic text-slate-400" {...props} />,

                                                    // Intercept images to render badges
                                                    img: ({ src, alt }) => {
                                                        if (src === 'badge' && alt?.startsWith('SOURCE:')) {
                                                            const sourceName = alt.replace('SOURCE:', '');
                                                            return <SourceBadge source={sourceName} />;
                                                        }
                                                        // Fallback for real images (disabled for safety or rendered normally)
                                                        return null;
                                                    }
                                                }}
                                            >
                                                {preprocessMarkdown(msg.content)}
                                            </ReactMarkdown>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            <div className="px-6 py-3 bg-white/5 border-t border-white/5 flex justify-between items-center bg-slate-950/40">
                <span className="text-[8px] font-bold text-slate-600 uppercase tracking-widest">
                    Verification Protocol Active
                </span>
                <div className="flex gap-2">
                    <div className="w-1 h-1 rounded-full bg-emerald-500/40" />
                    <div className="w-1 h-1 rounded-full bg-cyan-500/40" />
                    <div className="w-1 h-1 rounded-full bg-amber-500/40" />
                </div>
            </div>
        </div>
    );
};
