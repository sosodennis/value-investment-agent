import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { EvidenceFact } from '@/types/agents/debate';
import { DebateFactSheet } from './DebateFactSheet';
import { DebateTranscript } from './DebateTranscript';

afterEach(cleanup);

describe('DebateTranscript', () => {
    it('pairs bull and bear arguments in their explicit rounds', () => {
        render(
            <DebateTranscript
                history={[
                    { name: 'ForensicAccountant', content: 'Bear round one', round_num: 1 },
                    { name: 'GrowthHunter', content: 'Bull round one', round_num: 1 },
                    { name: 'Judge', content: 'Round one review', round_num: 1 },
                ]}
            />
        );

        expect(screen.getByRole('region', { name: 'Round 1' })).toBeTruthy();
        expect(screen.getByRole('article', { name: 'Bull case' }).textContent).toContain(
            'Bull round one'
        );
        expect(screen.getByRole('article', { name: 'Bear case' }).textContent).toContain(
            'Bear round one'
        );
        expect(screen.getByRole('article', { name: 'Moderator review' }).textContent).toContain(
            'Round one review'
        );
    });

    it('preserves legacy message order when round data is absent', () => {
        render(
            <DebateTranscript
                history={[
                    { name: 'GrowthHunter', content: 'First legacy argument' },
                    { name: 'ForensicAccountant', content: 'Second legacy argument' },
                ]}
            />
        );

        const first = screen.getByRole('article', { name: 'Bull transcript message 1' });
        const second = screen.getByRole('article', { name: 'Bear transcript message 2' });
        expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(screen.queryByRole('region', { name: 'Round 1' })).toBeNull();
    });

    it('scrolls to and focuses evidence when a fact citation is selected', () => {
        const facts: EvidenceFact[] = [
            {
                fact_id: 'F001',
                source_type: 'financials',
                source_weight: 'HIGH',
                summary: 'Revenue increased year over year.',
            },
        ];

        render(
            <>
                <DebateTranscript
                    history={[{ name: 'GrowthHunter', content: 'Revenue improved [Fact: F001].' }]}
                />
                <DebateFactSheet facts={facts} />
            </>
        );

        const evidence = document.getElementById('fact-F001');
        expect(evidence).toBeTruthy();
        if (!evidence) throw new Error('Evidence fact was not rendered.');
        const scrollIntoView = vi.fn();
        Object.defineProperty(evidence, 'scrollIntoView', {
            configurable: true,
            value: scrollIntoView,
        });

        fireEvent.click(screen.getByRole('button', { name: 'Show evidence F001' }));

        expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'center' });
        expect(document.activeElement).toBe(evidence);
    });
});
