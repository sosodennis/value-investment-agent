import { describe, expect, it } from 'vitest';
import { groupDebateHistoryByRound } from './debate-transcript-model';

describe('groupDebateHistoryByRound', () => {
    it('pairs bull and bear arguments by their explicit round number', () => {
        const result = groupDebateHistoryByRound([
            { name: 'ForensicAccountant', content: 'Bear round two', round_num: 2 },
            { name: 'GrowthHunter', content: 'Bull round one', round_num: 1 },
            { name: 'ForensicAccountant', content: 'Bear round one', round_num: 1 },
            { name: 'Judge', content: 'Moderator round one', round_num: 1 },
            { name: 'GrowthHunter', content: 'Bull round two', round_num: 2 },
            { name: 'Judge', content: 'Moderator round two', round_num: 2 },
        ]);

        expect(result.rounds.map(({ roundNum }) => roundNum)).toEqual([1, 2]);
        expect(result.rounds[0].bull[0].content).toBe('Bull round one');
        expect(result.rounds[0].bear[0].content).toBe('Bear round one');
        expect(result.rounds[0].moderator[0].content).toBe('Moderator round one');
        expect(result.rounds[1].bull[0].content).toBe('Bull round two');
        expect(result.rounds[1].bear[0].content).toBe('Bear round two');
        expect(result.rounds[1].moderator[0].content).toBe('Moderator round two');
        expect(result.unsequenced).toEqual([]);
    });

    it('keeps legacy and unknown-speaker messages in transcript order', () => {
        const legacy = { name: 'GrowthHunter', content: 'Legacy message' };
        const unknown = { name: 'Observer', content: 'Additional note', round_num: 1 };

        const result = groupDebateHistoryByRound([legacy, unknown]);

        expect(result.rounds).toEqual([]);
        expect(result.unsequenced).toEqual([legacy, unknown]);
    });
});
