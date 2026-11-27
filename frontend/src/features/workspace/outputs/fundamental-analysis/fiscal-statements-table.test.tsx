import { useState } from 'react';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { loadStatementReadFixture } from '@/test-fixtures/statement-read';
import { EvidenceInspector, type EvidenceSelection } from '../../workspace-evidence-inspector';
import { projectFiscalStatements } from './fiscal-statements-model';
import { FiscalStatementsTable } from './fiscal-statements-table';

afterEach(cleanup);
const reference = { artifact_id: 'saved-ttm', download_url: '/api/v1/artifacts/saved-ttm?thread_id=thread-1', type: 'financial_reports' };

describe('fiscal statement table and source inspection', () => {
    it('follows TTM to the derived final quarter and signed YTD/FY original inputs', () => {
        const report = projectFiscalStatements({ saved: loadStatementReadFixture('ttm'), reference, threadId: 'thread-1' });
        function Harness() {
            const [selected, setSelected] = useState<EvidenceSelection | null>(null);
            return <><FiscalStatementsTable report={report} selectedPeriod={null} onSelectEvidence={setSelected} /><EvidenceInspector items={report.evidence} selected={selected} onSelect={setSelected} /></>;
        }
        render(<Harness />);
        fireEvent.click(within(screen.getByRole('article', { name: 'TTM financial statements' })).getAllByRole('button', { name: /Inspect Revenue · ttm/ })[0]);
        let lineage = screen.getByRole('region', { name: 'Statement lineage' });
        const quarters = within(lineage).getAllByRole('button', { name: /\+1 · input Revenue · quarter/ });
        expect(quarters).toHaveLength(4);
        fireEvent.click(quarters[3]);
        lineage = screen.getByRole('region', { name: 'Statement lineage' });
        expect(screen.getByLabelText('Original value · full precision')).toHaveProperty('value', '89498000000');
        fireEvent.click(within(lineage).getByRole('button', { name: /−1 · input Revenue · reported ytd/ }));
        expect(screen.getByLabelText('Original value · full precision')).toHaveProperty('value', '293787000000');
        const source = screen.getByRole('link', { name: 'Open source document' });
        expect(source.getAttribute('href')).toMatch(/^https:\/\/www.sec.gov\//);
        screen.getByText('Reported raw text');
        screen.getByText('Reported decimals');
        screen.getByText('Archive member hash');
        screen.getByText('Source binding');
        expect(document.activeElement?.getAttribute('aria-label')).toMatch(/reported ytd.*details/);
        fireEvent.click(within(screen.getByRole('region', { name: 'Statement lineage' })).getByRole('button', { name: /parent Revenue · quarter · 2023-07-02 to 2023-09-30/ }));
        expect(screen.getByLabelText('Original value · full precision')).toHaveProperty('value', '89498000000');
    });

    it('shows actual instants, 371-day TTM coverage and the retained Apple FX missing reason', () => {
        const report = projectFiscalStatements({ saved: loadStatementReadFixture('ttm'), reference, threadId: 'thread-1' });
        render(<FiscalStatementsTable report={report} selectedPeriod={report.columns[0].id} />);
        const balance = screen.getByRole('region', { name: 'Balance sheet' });
        expect(within(balance).queryByText(/371 days/)).toBeNull();
        expect(within(balance).getAllByText('As of 2023-09-30').length).toBeGreaterThan(0);
        expect(screen.getAllByText(/371 days/).length).toBeGreaterThan(0);
        expect(screen.getAllByText(/required quarter unavailable/).length).toBe(5);
        expect(screen.getByText(/Opening and closing cash are period boundaries/)).toBeTruthy();
        const fx = report.tables.find((table) => table.kind === 'cash_flow')?.rows.find((row) => row.id === 'effect_of_exchange_rates_on_cash');
        expect(fx?.cells.every((cell) => cell.evidence.value.includes('required_quarter_unavailable'))).toBe(true);
        expect(fx?.cells.every((cell) => cell.evidence.value !== '0')).toBe(true);
    });

    it('presents a conflict as an inspectable reason rather than a number', () => {
        const saved = loadStatementReadFixture('quarter');
        if (saved.read.kind !== 'fiscal') throw new Error('Fiscal fixture required');
        const root = saved.read.result.rows[0].cells[0];
        const node = saved.read.result.evidence.nodes.find((item) => item.node_id === root.node_id);
        if (!node) throw new Error('Fixture root required');
        node.availability = 'conflict'; node.value = null; node.reason_code = 'conflicting_reported_inputs';
        saved.read.result.rows[0].cells[0] = { kind: 'conflict', node_id: root.node_id, reason_code: 'conflicting_reported_inputs' };
        const report = projectFiscalStatements({ saved, reference, threadId: 'thread-1' });
        render(<FiscalStatementsTable report={report} selectedPeriod={null} onSelectEvidence={() => undefined} />);
        expect(screen.getByRole('button', { name: /Inspect Revenue · quarter · 2022-09-25 to 2022-12-31/ }).textContent).toBe('conflict · conflicting_reported_inputs');
        screen.getByText('conflicting reported inputs');
    });
});
