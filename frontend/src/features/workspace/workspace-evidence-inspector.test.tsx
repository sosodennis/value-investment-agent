import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { adaptAgentOutput } from '@/types/agents/output-adapter';
import type { AgentInfo, StandardAgentOutput } from '@/types/agents';
import { buildEvidenceItems, EvidenceInspector } from './workspace-evidence-inspector';

const agent: AgentInfo = {
    id: 'fundamental_analysis',
    name: 'Fundamental Analyst',
    description: 'Fundamental analysis',
    avatar: 'FA',
    status: 'done',
};

describe('buildEvidenceItems', () => {
    afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
    it('keeps unverified legacy preview financial values out of the Fundamental evidence inventory', () => {
        const output: StandardAgentOutput = {
            kind: 'fundamental_analysis.output', version: 'v1', summary: 'AAPL report',
            preview: { intrinsic_value: 123, distribution_summary: { mean: 456 } },
        };
        const items = buildEvidenceItems(agent, adaptAgentOutput(agent.id, output));
        expect(items.map((item) => item.title)).toEqual(['Fundamental Analyst summary']);
    });

    it('renders selected service fact provenance and marks absent metadata unavailable', () => {
        const item = {
            id: 'fundamental:service-fact:fact-1',
            title: 'Service fact · Revenue',
            value: '12,500',
            source: 'filing · https://www.sec.gov/Archives/filing.xml',
            period: '2025-01-01 → 2025-12-31',
            confidence: 'verified · mapping high',
            factId: 'fact-1',
            accessionNumber: '0000000000-26-000001',
            filedAt: '2026-01-01T00:00:00Z',
            availableAt: '2026-01-02T03:05:00Z',
            capturedAt: '2026-01-02T03:04:05Z',
            parserVersion: 'arelle-2.38.0',
            taxonomyVersion: 'us-gaap-2025',
            mappingVersion: 'mapping-v3',
            sourceHash: 'a'.repeat(64),
            snapshotId: 'snapshot-1',
            snapshotManifestDigest: 'b'.repeat(64),
            unit: 'USD',
            scale: 3,
            issueCodes: [],
        };

        render(<EvidenceInspector items={[item]} selected={item} onSelect={() => undefined} />);

        screen.getByText('fact-1');
        screen.getByText('0000000000-26-000001');
        screen.getByText('arelle-2.38.0');
        screen.getByText('snapshot-1');
        expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0);
        expect(screen.queryByText(/SEC XBRL concept/)).toBeNull();
    });

    it('puts the selected detail before the collapsed inventory and resets feedback on selection', async () => {
        const writeText = vi.fn().mockResolvedValue(undefined);
        vi.stubGlobal('navigator', { clipboard: { writeText } });
        const first = { id: 'first', title: 'Revenue', value: '331839000000', displayValue: 'USD 331.84B' };
        const second = { id: 'second', title: 'WACC', value: '0.1028', displayValue: '10.28%' };
        const { rerender } = render(<EvidenceInspector items={[first, second]} selected={first} onSelect={() => undefined} />);
        const detail = screen.getByLabelText('Original value · full precision');
        const inventory = screen.getByText('Browse all evidence (2)');
        expect(detail.compareDocumentPosition(inventory) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(inventory.closest('details')?.open).toBe(false);
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Copy original value' })));
        expect(writeText).toHaveBeenCalledWith(first.value);
        screen.getByText('Original value copied.');
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Copy displayed value' })));
        expect(writeText).toHaveBeenLastCalledWith(first.displayValue);
        screen.getByText('Displayed value copied.');
        rerender(<EvidenceInspector items={[first, second]} selected={second} onSelect={() => undefined} />);
        expect(screen.queryByText('Displayed value copied.')).toBeNull();
        expect(screen.getByLabelText('Original value · full precision')).toHaveProperty('value', second.value);
    });

    it('reports success only after clipboard completion and offers selectable raw text on rejection', async () => {
        let rejectCopy: (reason: Error) => void = () => undefined;
        const writeText = vi.fn(() => new Promise<void>((_resolve, reject) => { rejectCopy = reject; }));
        vi.stubGlobal('navigator', { clipboard: { writeText } });
        const item = { id: 'first', title: 'Revenue', value: '331839000000.00001', displayValue: 'USD 331.84B' };
        render(<EvidenceInspector items={[item]} selected={item} onSelect={() => undefined} />);
        fireEvent.click(screen.getByRole('button', { name: 'Copy original value' }));
        screen.getByText('Copying value…');
        expect(screen.queryByText('Original value copied.')).toBeNull();
        await act(async () => rejectCopy(new Error('Permission denied')));
        screen.getByText(/Clipboard unavailable/);
        const raw = screen.getByLabelText<HTMLTextAreaElement>('Original value · full precision');
        expect(document.activeElement).toBe(raw);
        expect(raw.value.slice(raw.selectionStart, raw.selectionEnd)).toBe(item.value);
        writeText.mockRejectedValueOnce(new Error('Permission denied'));
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Copy displayed value' })));
        expect(screen.getByLabelText('Displayed value for manual copy')).toHaveProperty('value', item.displayValue);
    });
});
