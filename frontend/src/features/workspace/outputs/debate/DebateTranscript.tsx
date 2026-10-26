
import React from 'react';
import ReactMarkdown from 'react-markdown';
import { TrendingUp, TrendingDown, Gavel, Database, Newspaper, BarChart4, ShieldCheck } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';

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
    let variant: 'default' | 'success' | 'warning' | 'outline' = 'outline';
    let icon = <ShieldCheck className="w-2.5 h-2.5" />;

    if (type === 'fact') {
        if (source.startsWith('F')) {
            variant = 'success';
            icon = <Database className="w-2.5 h-2.5" />;
        } else if (source.startsWith('N')) {
            variant = 'default';
            icon = <Newspaper className="w-2.5 h-2.5" />;
        } else if (source.startsWith('T')) {
            variant = 'warning';
            icon = <BarChart4 className="w-2.5 h-2.5" />;
        }
    } else if (source.includes('Financials') || source.includes('SEC')) {
        variant = 'success';
        icon = <Database className="w-2.5 h-2.5" />;
    } else if (source.includes('News')) {
        variant = 'default';
        icon = <Newspaper className="w-2.5 h-2.5" />;
    } else if (source.includes('Technicals')) {
        variant = 'warning';
        icon = <BarChart4 className="w-2.5 h-2.5" />;
    }

    const badge = <Badge variant={variant} className="mx-1 inline-flex align-middle gap-1">{icon}{source}</Badge>;
    return type === 'fact' && onClick ? (
        <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-auto min-h-0 rounded-md p-0 align-middle"
            onClick={onClick}
            aria-label={`Show evidence ${source}`}
        >
            {badge}
        </Button>
    ) : badge;
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
    const visibleMessages = history.filter((message) => message.role !== 'system');

    const scrollToFact = (factId: string) => {
        const el = document.getElementById(`fact-${factId}`);
        if (!el) return;
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add('ring-2', 'ring-primary/60');
        window.setTimeout(() => {
            el.classList.remove('ring-2', 'ring-primary/60');
        }, 1400);
    };

    return (
        <Card className="mt-4 overflow-hidden">
            <CardHeader className="flex-row items-center justify-between gap-3 bg-muted/40 p-4">
                <div className="flex items-center gap-3">
                    <Gavel aria-hidden="true" className="size-4 text-primary" />
                    <h3 className="text-base font-semibold">Debate transcript</h3>
                </div>
                <Badge variant="outline">{visibleMessages.length} messages</Badge>
            </CardHeader>

            <CardContent className="max-h-[600px] overflow-y-auto bg-background p-4 sm:p-5">
                <div className="space-y-10 relative">
                    {visibleMessages.map((msg, idx) => {
                        const isBull = msg.name === 'GrowthHunter';
                        const isBear = msg.name === 'ForensicAccountant';
                        const isJudge = msg.name === 'Judge';

                        let avatarIcon = <div className="w-full h-full bg-muted" />;
                        const nameDisplay = msg.name || 'Agent';
                        let roleColor = "text-muted-foreground";
                        let ringColor = "border-border/30";
                        let accentBorder = 'border-l-border/40';

                        if (isBull) {
                            avatarIcon = <TrendingUp className="w-4 h-4 text-success " />;
                            roleColor = "text-success";
                            ringColor = "border-success/30";
                            accentBorder = 'border-l-success/50';
                        } else if (isBear) {
                            avatarIcon = <TrendingDown className="w-4 h-4 text-destructive" />;
                            roleColor = "text-destructive";
                            ringColor = "border-destructive/30";
                            accentBorder = 'border-l-destructive/50';
                        } else if (isJudge) {
                            avatarIcon = <Gavel className="w-4 h-4 text-primary" />;
                            roleColor = "text-primary";
                            ringColor = "border-primary/30";
                            accentBorder = 'border-l-primary/50';
                        }

                        return (
                            <div
                                key={idx}
                                className="flex gap-6 group relative "
                                style={{ animationDelay: `${idx * 0.1}s` }}
                            >
                                <div className={`z-10 w-9 h-9 rounded-full border-2 ${ringColor} bg-background flex items-center justify-center shrink-0  transition-transform duration-300 group-hover:scale-110`}>
                                    {avatarIcon}
                                </div>
                                <div className="flex flex-col gap-2 w-full min-w-0">
                                    <div className="flex items-center gap-3">
                                        <span className={`text-[10px] font-black uppercase tracking-[0.2em] ${roleColor} flex items-center gap-2`}>
                                            {nameDisplay}
                                            <span className="w-1 h-1 rounded-full bg-muted" />
                                            <span className="text-muted-foreground font-medium tracking-normal lowercase">{msg.role}</span>
                                        </span>
                                        <div className="h-px bg-muted/50 flex-grow" />
                                    </div>
                                    <div className={`p-5 rounded-lg border border-border/10 border-l-2 bg-muted/50 transition duration-300 group-hover:border-border/30 ${accentBorder}`}>
                                        <div className="text-[14px] leading-relaxed text-muted-foreground font-sans tracking-tight break-words">
                                            <ReactMarkdown
                                                components={{
                                                    p: (props) => <p className="mb-4 last:mb-0" {...props} />,
                                                    strong: (props) => <strong className="font-bold text-foreground tracking-tight" {...props} />,
                                                    em: (props) => <em className="italic text-muted-foreground border-b border-border/30 pb-0.5" {...props} />,
                                                    h1: (props) => <h1 className="text-lg font-black text-foreground mt-6 mb-3 uppercase tracking-wider flex items-center gap-2 before:content-[''] before:w-1 before:h-4 before:bg-primary" {...props} />,
                                                    h2: (props) => <h2 className="text-base font-bold text-foreground mt-5 mb-2 border-b border-border/30 pb-1" {...props} />,
                                                    ul: (props) => <ul className="space-y-2 mb-4 list-none pl-1" {...props} />,
                                                    li: (props) => (
                                                        <li className="relative pl-5 mb-3 leading-relaxed before:content-['›'] before:absolute before:left-0 before:top-0 before:text-primary before:font-bold before:text-lg before:leading-none" {...props} />
                                                    ),
                                                    blockquote: (props) => (
                                                        <blockquote className="border-l-2 border-border/50 pl-4 py-1 my-4 italic text-muted-foreground bg-white/2 rounded-r" {...props} />
                                                    ),
                                                    code: (props) => (
                                                        <code className="bg-background px-1.5 py-0.5 rounded font-mono text-[13px] text-primary border border-border/30" {...props} />
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
            </CardContent>
        </Card>
    );
};
