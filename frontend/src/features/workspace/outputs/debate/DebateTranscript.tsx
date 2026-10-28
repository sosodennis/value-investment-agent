import ReactMarkdown from 'react-markdown';
import { BarChart4, Database, Gavel, Newspaper, ShieldCheck, TrendingDown, TrendingUp } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { DebateHistoryMessage } from '@/types/agents/debate';
import { groupDebateHistoryByRound, type DebateSpeaker } from './debate-transcript-model';

interface DebateTranscriptProps {
    history: DebateHistoryMessage[];
}

type SourceBadgeProps = {
    source: string;
    type?: 'source' | 'fact';
    onFactSelect?: (factId: string) => void;
};

function SourceBadge({ source, type = 'source', onFactSelect }: SourceBadgeProps) {
    const icon = type === 'fact' ? <FactIcon factId={source} /> : <SourceIcon source={source} />;
    const variant = type === 'fact' ? factBadgeVariant(source) : 'outline';
    const sourceBadge = (
        <Badge variant={variant} className="mx-1 inline-flex align-middle gap-1">
            {icon}
            {source}
        </Badge>
    );

    if (type !== 'fact' || !onFactSelect) return sourceBadge;

    return (
        <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-auto min-h-0 rounded p-0 align-middle"
            onClick={() => onFactSelect(source)}
            aria-label={`Show evidence ${source}`}
        >
            {sourceBadge}
        </Button>
    );
}

function SourceIcon({ source }: { source: string }) {
    if (source.includes('Financial') || source.includes('SEC')) return <Database aria-hidden="true" className="size-3" />;
    if (source.includes('News')) return <Newspaper aria-hidden="true" className="size-3" />;
    if (source.includes('Technical')) return <BarChart4 aria-hidden="true" className="size-3" />;
    return <ShieldCheck aria-hidden="true" className="size-3" />;
}

function FactIcon({ factId }: { factId: string }) {
    if (factId.startsWith('F')) return <Database aria-hidden="true" className="size-3" />;
    if (factId.startsWith('N')) return <Newspaper aria-hidden="true" className="size-3" />;
    if (factId.startsWith('T')) return <BarChart4 aria-hidden="true" className="size-3" />;
    return <ShieldCheck aria-hidden="true" className="size-3" />;
}

function factBadgeVariant(source: string): 'success' | 'default' | 'warning' | 'outline' {
    if (source.startsWith('F')) return 'success';
    if (source.startsWith('N')) return 'default';
    if (source.startsWith('T')) return 'warning';
    return 'outline';
}

function preprocessMarkdown(content: string) {
    return content
        .replace(/[`]?\[Source:\s*([^\]]+)\][`]?/g, (_, source: string) => `![SOURCE:${source}](badge)`)
        .replace(/[`]?\[Fact:\s*([^\]]+)\][`]?/g, (_, factId: string) => `![FACT:${factId}](badge)`);
}

function getSpeaker(name: string | undefined): DebateSpeaker | undefined {
    if (name === 'GrowthHunter') return 'bull';
    if (name === 'ForensicAccountant') return 'bear';
    if (name === 'Judge') return 'moderator';
    return undefined;
}

function scrollToFact(factId: string) {
    const target = document.getElementById(`fact-${factId}`);
    if (!target) return;

    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    target.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' });
    target.focus({ preventScroll: true });
}

function MessageBody({ message }: { message: DebateHistoryMessage }) {
    return (
        <div className="min-w-0 break-words text-sm leading-6 text-foreground">
            <ReactMarkdown
                components={{
                    p: ({ children }) => <p className="mb-3 last:mb-0" >{children}</p>,
                    strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                    em: ({ children }) => <em className="italic">{children}</em>,
                    h1: ({ children }) => <h4 className="mb-2 mt-4 text-base font-semibold first:mt-0">{children}</h4>,
                    h2: ({ children }) => <h5 className="mb-2 mt-4 text-sm font-semibold first:mt-0">{children}</h5>,
                    ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>,
                    ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>,
                    li: ({ children }) => <li>{children}</li>,
                    blockquote: ({ children }) => <blockquote className="my-3 border-l-2 border-border pl-3 text-muted-foreground">{children}</blockquote>,
                    code: ({ children }) => <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{children}</code>,
                    img: ({ src, alt }) => {
                        if (src !== 'badge' || !alt) return null;
                        if (alt.startsWith('SOURCE:')) return <SourceBadge source={alt.slice('SOURCE:'.length)} />;
                        if (alt.startsWith('FACT:')) {
                            return <SourceBadge source={alt.slice('FACT:'.length)} type="fact" onFactSelect={scrollToFact} />;
                        }
                        return null;
                    },
                }}
            >
                {preprocessMarkdown(message.content)}
            </ReactMarkdown>
        </div>
    );
}

function RoundRoleCard({ speaker, messages }: { speaker: DebateSpeaker; messages: DebateHistoryMessage[] }) {
    const presentation = {
        bull: { label: 'Bull case', icon: TrendingUp, tone: 'text-success' },
        bear: { label: 'Bear case', icon: TrendingDown, tone: 'text-destructive' },
        moderator: { label: 'Moderator review', icon: Gavel, tone: 'text-primary' },
    }[speaker];
    const SpeakerIcon = presentation.icon;

    return (
        <article aria-label={presentation.label} className="min-w-0 rounded-md border bg-card p-4">
            <header className="mb-3 flex items-center gap-2">
                <SpeakerIcon aria-hidden="true" className={`size-4 ${presentation.tone}`} />
                <h4 className={`text-sm font-semibold ${presentation.tone}`}>{presentation.label}</h4>
            </header>
            {messages.length > 0 ? (
                <div className="space-y-4">
                    {messages.map((message, index) => (
                        <div key={`${message.round_num ?? 'legacy'}-${message.name ?? 'agent'}-${index}`}>
                            {message.role && <p className="mb-2 text-xs text-muted-foreground">{message.role}</p>}
                            <MessageBody message={message} />
                        </div>
                    ))}
                </div>
            ) : (
                <p className="text-sm text-muted-foreground">
                    No {speaker === 'moderator' ? 'moderator review' : `${speaker} argument`} was recorded for this round.
                </p>
            )}
        </article>
    );
}

function TranscriptMessage({ message, index }: { message: DebateHistoryMessage; index: number }) {
    const speaker = getSpeaker(message.name);
    const label = speaker === 'bull'
        ? 'Bull'
        : speaker === 'bear'
          ? 'Bear'
          : speaker === 'moderator'
            ? 'Moderator'
            : message.name || 'Agent';
    const SpeakerIcon = speaker === 'bull' ? TrendingUp : speaker === 'bear' ? TrendingDown : Gavel;
    const tone = speaker === 'bull'
        ? 'text-success'
        : speaker === 'bear'
          ? 'text-destructive'
          : speaker === 'moderator'
            ? 'text-primary'
            : 'text-muted-foreground';

    return (
        <article aria-label={`${label} transcript message ${index + 1}`} className="grid min-w-0 grid-cols-[1rem_minmax(0,1fr)] gap-3 border-b py-4 last:border-b-0">
            <SpeakerIcon aria-hidden="true" className={`mt-1 size-4 ${tone}`} />
            <div className="min-w-0">
                <header className="mb-2 flex flex-wrap items-center gap-2">
                    <h4 className={`text-sm font-semibold ${tone}`}>{label}</h4>
                    {message.role && <Badge variant="outline">{message.role}</Badge>}
                </header>
                <MessageBody message={message} />
            </div>
        </article>
    );
}

export function DebateTranscript({ history }: DebateTranscriptProps) {
    const visibleMessages = history.filter((message) => message.role !== 'system');
    if (visibleMessages.length === 0) return null;

    const { rounds, unsequenced } = groupDebateHistoryByRound(visibleMessages);
    const hasRoundData = rounds.length > 0;

    return (
        <section className="mt-6 min-w-0" aria-labelledby="debate-transcript-title">
            <header className="mb-4 flex flex-wrap items-center justify-between gap-3 border-y py-3">
                <div className="flex items-center gap-2">
                    <Gavel aria-hidden="true" className="size-4 text-primary" />
                    <h3 id="debate-transcript-title" className="text-base font-semibold">
                        {hasRoundData ? 'Debate rounds' : 'Debate transcript'}
                    </h3>
                </div>
                <Badge variant="outline">
                    {hasRoundData ? `${rounds.length} rounds` : `${visibleMessages.length} messages`}
                </Badge>
            </header>

            {hasRoundData ? (
                <div className="space-y-5">
                    {rounds.map((round) => (
                        <section key={round.roundNum} aria-label={`Round ${round.roundNum}`} className="min-w-0 space-y-3">
                            <h4 className="text-sm font-semibold tabular-nums">Round {round.roundNum}</h4>
                            <div className="grid min-w-0 grid-cols-1 gap-3 lg:grid-cols-2">
                        <RoundRoleCard speaker="bull" messages={round.bull} />
                        <RoundRoleCard speaker="bear" messages={round.bear} />
                            </div>
                    {round.moderator.length > 0 && (
                        <RoundRoleCard speaker="moderator" messages={round.moderator} />
                    )}
                        </section>
                    ))}
                    {unsequenced.length > 0 && (
                        <section aria-label="Additional transcript entries" className="border-t pt-4">
                            <h4 className="mb-2 text-sm font-semibold">Additional transcript entries</h4>
                            <div>
                                {unsequenced.map((message, index) => <TranscriptMessage key={index} message={message} index={index} />)}
                            </div>
                        </section>
                    )}
                </div>
            ) : (
                <div aria-label="Debate transcript messages">
                    {visibleMessages.map((message, index) => <TranscriptMessage key={index} message={message} index={index} />)}
                </div>
            )}
        </section>
    );
}
