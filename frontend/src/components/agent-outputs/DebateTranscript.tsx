
import React from 'react';
import ReactMarkdown from 'react-markdown';
import { TrendingUp, TrendingDown, Gavel, Database, Newspaper, BarChart4, ShieldCheck } from 'lucide-react';

interface Message {
    name?: string;
    role?: string; // 'system' | 'human' | 'ai'
    content: string;
}

interface DebateTranscriptProps {
    history: Message[];
}

const SourceBadge = ({
    source,
    type = 'source',
    onClick,
}: {
    source: string;
    type?: 'source' | 'fact';
    onClick?: () => void;
}) => {
    let color = "bg-slate-500/10 text-slate-400 border-slate-500/20"; // Default
    let icon = <ShieldCheck className="w-2.5 h-2.5" />;

    if (type === 'fact') {
        if (source.startsWith('F')) {
            color = "bg-emerald-500/10 text-emerald-400 border-emerald-500/25 shadow-[0_0_10px_rgba(16,185,129,0.1)]";
            icon = <Database className="w-2.5 h-2.5" />;
        } else if (source.startsWith('N')) {
            color = "bg-cyan-500/10 text-cyan-400 border-cyan-500/25 shadow-[0_0_10px_rgba(6,182,212,0.1)]";
            icon = <Newspaper className="w-2.5 h-2.5" />;
        } else if (source.startsWith('T')) {
            color = "bg-amber-500/10 text-amber-400 border-amber-500/25 shadow-[0_0_10px_rgba(245,158,11,0.1)]";
            icon = <BarChart4 className="w-2.5 h-2.5" />;
        }

        return (
            <span
                onClick={onClick}
                role={onClick ? "button" : undefined}
                className={`inline-flex items-center px-2 py-0.5 rounded border text-[9px] font-black tracking-widest mx-1 cursor-pointer transition-all duration-200 align-middle shadow-sm hover:scale-105 active:scale-95 ${color}`}
            >
                <span className="mr-1.5 opacity-80">{icon}</span>
                {source}
            </span>
        );
    }

    if (source.includes("Financials") || source.includes("SEC")) {
        color = "bg-emerald-500/10 text-emerald-400 border-emerald-500/25 hover:bg-emerald-500/20 hover:text-emerald-300 hover:border-emerald-500/40";
        icon = <Database className="w-2.5 h-2.5" />;
    } else if (source.includes("News")) {
        color = "bg-cyan-500/10 text-cyan-400 border-cyan-500/25 hover:bg-cyan-500/20 hover:text-cyan-300 hover:border-cyan-500/40";
        icon = <Newspaper className="w-2.5 h-2.5" />;
    } else if (source.includes("Technicals")) {
        color = "bg-amber-500/10 text-amber-400 border-amber-500/25 hover:bg-amber-500/20 hover:text-amber-300 hover:border-amber-500/40";
        icon = <BarChart4 className="w-2.5 h-2.5" />;
    }

    return (
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[9px] font-black uppercase tracking-widest mx-1 cursor-pointer transition-all duration-200 align-middle shadow-sm ${color}`}>
            <span className="mr-1.5 opacity-80">{icon}</span>
            {source}
        </span>
    );
};

// Helper: Convert [Source: X] tags to Markdown image syntax
// This allows ReactMarkdown to parse them as images, which we then intercept
const preprocessMarkdown = (content: string) => {
    // Regex matches [Source: X] possibly wrapped in backticks
    let processed = content.replace(/[`]?\[Source:\s*([^\]]+)\][`]?/g, (_, source) => {
        return `![SOURCE:${source}](badge)`;
    });

    // Regex matches [Fact: X] possibly wrapped in backticks
    processed = processed.replace(/[`]?\[Fact:\s*([^\]]+)\][`]?/g, (_, factId) => {
        return `![FACT:${factId}](badge)`;
    });

    return processed;
};

export const DebateTranscript: React.FC<DebateTranscriptProps> = ({ history }) => {
    if (!history || history.length === 0) return null;

    const scrollToFact = (factId: string) => {
        const el = document.getElementById(`fact-${factId}`);
        if (!el) return;
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("ring-1", "ring-cyan-400/60", "shadow-[0_0_20px_rgba(6,182,212,0.2)]");
        window.setTimeout(() => {
            el.classList.remove("ring-1", "ring-cyan-400/60", "shadow-[0_0_20px_rgba(6,182,212,0.2)]");
        }, 1400);
    };

    return (
        <div className="tech-card mt-8 animate-fade-in">
            {/* Terminal Header */}
            <div className="px-5 py-3 border-b border-white/5 bg-slate-900/40 flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className="flex gap-1.5">
                        <div className="w-2.5 h-2.5 rounded-full bg-rose-500/20 border border-rose-500/40" />
                        <div className="w-2.5 h-2.5 rounded-full bg-amber-500/20 border border-amber-500/40" />
                        <div className="w-2.5 h-2.5 rounded-full bg-emerald-500/20 border border-emerald-500/40" />
                    </div>
                    <div className="h-4 w-px bg-white/10 mx-1" />
                    <h3 className="text-label flex items-center gap-2">
                        <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse shadow-[0_0_8px_rgba(6,182,212,0.6)]"></span>
                        Agent Intelligence Transcript
                    </h3>
                </div>
                <div className="flex items-center gap-3">
                    <span className="text-[8px] font-black text-emerald-500/80 tracking-[0.2em] border border-emerald-500/20 px-2 py-0.5 rounded bg-emerald-500/5">
                        LIVE_FEED
                    </span>
                    <span className="text-[10px] text-slate-600 font-mono">v1.2.4</span>
                </div>
            </div>

            <div className="p-6 max-h-[600px] overflow-y-auto custom-scrollbar bg-slate-950/40">
                <div className="space-y-10 relative">
                    {/* Vertical line connector */}
                    <div className="absolute left-4 top-0 bottom-0 w-px bg-gradient-to-b from-white/5 via-white/5 to-transparent" />

                    {history.map((msg, idx) => {
                        // Filter out system messages
                        if (msg.role === 'system') return null;

                        const isBull = msg.name === 'GrowthHunter';
                        const isBear = msg.name === 'ForensicAccountant';
                        const isJudge = msg.name === 'Judge';

                        let avatarIcon = <div className="w-full h-full bg-slate-700" />;
                        const nameDisplay = msg.name || 'Agent';
                        let roleColor = "text-slate-400";
                        let ringColor = "border-slate-800";
                        let bgColor = "from-slate-900/40 to-slate-900/10";
                        let glowColor = "group-hover:shadow-[0_0_20px_-5px_rgba(148,163,184,0.1)]";

                        if (isBull) {
                            avatarIcon = <TrendingUp className="w-4 h-4 text-emerald-400 animate-pulse" />;
                            roleColor = "text-emerald-400";
                            ringColor = "border-emerald-500/30";
                            bgColor = "from-emerald-950/20 to-slate-900/20";
                            glowColor = "group-hover:shadow-[0_0_20px_-5px_rgba(16,185,129,0.2)]";
                        } else if (isBear) {
                            avatarIcon = <TrendingDown className="w-4 h-4 text-rose-400" />;
                            roleColor = "text-rose-400";
                            ringColor = "border-rose-500/30";
                            bgColor = "from-rose-950/20 to-slate-900/20";
                            glowColor = "group-hover:shadow-[0_0_20px_-5px_rgba(244,63,94,0.2)]";
                        } else if (isJudge) {
                            avatarIcon = <Gavel className="w-4 h-4 text-cyan-400" />;
                            roleColor = "text-cyan-400";
                            ringColor = "border-cyan-500/30";
                            bgColor = "from-cyan-950/20 to-slate-900/20";
                            glowColor = "group-hover:shadow-[0_0_20px_-5px_rgba(6,182,212,0.2)]";
                        }

                        return (
                            <div key={idx} className="flex gap-6 group relative animate-slide-up" style={{ animationDelay: `${idx * 0.1}s` }}>
                                <div className={`z-10 w-9 h-9 rounded-full border-2 ${ringColor} bg-slate-950 flex items-center justify-center shrink-0 shadow-2xl transition-transform duration-300 group-hover:scale-110`}>
                                    {avatarIcon}
                                </div>
                                <div className="flex flex-col gap-2 w-full min-w-0">
                                    <div className="flex items-center gap-3">
                                        <span className={`text-[10px] font-black uppercase tracking-[0.2em] ${roleColor} flex items-center gap-2`}>
                                            {nameDisplay}
                                            <span className="w-1 h-1 rounded-full bg-slate-700" />
                                            <span className="text-slate-600 font-medium tracking-normal lowercase">{msg.role}</span>
                                        </span>
                                        <div className="h-px bg-white/5 flex-grow" />
                                    </div>
                                    <div className={`p-5 rounded-2xl border border-white/5 bg-gradient-to-br ${bgColor} transition-all duration-300 ${glowColor} backdrop-blur-sm group-hover:border-white/10`}>
                                        <div className="text-[15px] leading-relaxed text-slate-300 font-sans tracking-tight">
                                            <ReactMarkdown
                                                components={{
                                                    p: (props) => <p className="mb-4 last:mb-0" {...props} />,
                                                    strong: (props) => <strong className="font-bold text-white tracking-tight" {...props} />,
                                                    em: (props) => <em className="italic text-slate-400 border-b border-white/5 pb-0.5" {...props} />,
                                                    h1: (props) => <h1 className="text-lg font-black text-white mt-6 mb-3 uppercase tracking-wider flex items-center gap-2 before:content-[''] before:w-1 before:h-4 before:bg-cyan-500" {...props} />,
                                                    h2: (props) => <h2 className="text-base font-bold text-white mt-5 mb-2 border-b border-white/5 pb-1" {...props} />,
                                                    ul: (props) => <ul className="space-y-2 mb-4 list-none pl-1" {...props} />,
                                                    li: (props) => (
                                                        <li className="relative pl-5 mb-3 leading-relaxed before:content-['›'] before:absolute before:left-0 before:top-0 before:text-cyan-500 before:font-bold before:text-lg before:leading-none" {...props} />
                                                    ),
                                                    blockquote: (props) => (
                                                        <blockquote className="border-l-2 border-slate-700 pl-4 py-1 my-4 italic text-slate-400 bg-white/2 rounded-r" {...props} />
                                                    ),
                                                    code: (props) => (
                                                        <code className="bg-slate-950 px-1.5 py-0.5 rounded font-mono text-[13px] text-cyan-400 border border-white/5" {...props} />
                                                    ),
                                                    // Intercept images to render badges
                                                    img: ({ src, alt }) => {
                                                        if (src === 'badge') {
                                                            if (alt?.startsWith('SOURCE:')) {
                                                                const sourceName = alt.replace('SOURCE:', '');
                                                                return <SourceBadge source={sourceName} />;
                                                            }
                                                            if (alt?.startsWith('FACT:')) {
                                                                const factId = alt.replace('FACT:', '');
                                                                return <SourceBadge source={factId} type="fact" onClick={() => scrollToFact(factId)} />;
                                                            }
                                                        }
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

            <div className="px-6 py-4 bg-slate-950/60 border-t border-white/5 flex justify-between items-center">
                <div className="flex items-center gap-4">
                    <span className="text-[9px] font-black text-slate-500 uppercase tracking-[0.3em] flex items-center gap-1.5">
                        <span className="w-1 h-1 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.4)]" />
                        Verification Protocol Active
                    </span>
                    <div className="h-4 w-px bg-white/5" />
                    <span className="text-[9px] font-mono text-slate-600">SHA-256: 8f2b...3e1a</span>
                </div>
                <div className="flex gap-3">
                    <div className="w-1.5 h-1.5 rounded-full bg-emerald-500/20" />
                    <div className="w-1.5 h-1.5 rounded-full bg-cyan-500/20" />
                    <div className="w-1.5 h-1.5 rounded-full bg-amber-500/20" />
                </div>
            </div>
        </div>
    );
};
