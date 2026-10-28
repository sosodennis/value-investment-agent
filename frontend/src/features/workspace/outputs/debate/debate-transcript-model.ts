import type { DebateHistoryMessage } from '@/types/agents/debate';

export type DebateSpeaker = 'bull' | 'bear' | 'moderator';

export interface DebateRoundTranscript {
    roundNum: number;
    bull: DebateHistoryMessage[];
    bear: DebateHistoryMessage[];
    moderator: DebateHistoryMessage[];
}

export interface DebateTranscriptSections {
    rounds: DebateRoundTranscript[];
    unsequenced: DebateHistoryMessage[];
}

const getSpeaker = (name: string | undefined): DebateSpeaker | undefined => {
    if (name === 'GrowthHunter') return 'bull';
    if (name === 'ForensicAccountant') return 'bear';
    if (name === 'Judge') return 'moderator';
    return undefined;
};

export function groupDebateHistoryByRound(
    history: DebateHistoryMessage[]
): DebateTranscriptSections {
    const rounds = new Map<number, DebateRoundTranscript>();
    const unsequenced: DebateHistoryMessage[] = [];

    for (const message of history) {
        const speaker = getSpeaker(message.name);
        const roundNum = message.round_num;
        if (!speaker || roundNum === undefined || !Number.isInteger(roundNum) || roundNum < 1) {
            unsequenced.push(message);
            continue;
        }

        let round = rounds.get(roundNum);
        if (!round) {
            round = { roundNum, bull: [], bear: [], moderator: [] };
            rounds.set(roundNum, round);
        }
        round[speaker].push(message);
    }

    return {
        rounds: [...rounds.values()].sort((left, right) => left.roundNum - right.roundNum),
        unsequenced,
    };
}
