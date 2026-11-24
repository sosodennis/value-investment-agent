import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { loadAnnualStatementFixture } from '@/test-fixtures/annual-statements';
import { EvidenceInspector } from '../../workspace-evidence-inspector';
import { projectAnnualStatements } from './annual-statements-model';
import { AnnualStatementsTable } from './annual-statements-table';

function report() {
    return projectAnnualStatements({ response: loadAnnualStatementFixture(), reference: { artifact_id: 'saved-statement', download_url: '/api/v1/artifacts/saved-statement', type: 'financial_reports' }, threadId: 'thread-1', companyName: 'Example Issuer', ticker: 'TEST' });
}

describe('annual statement comparison and inspection', () => {
    it('renders all statement names, actual dates, source coverage and zero/negative values', () => {
        render(<AnnualStatementsTable report={report()} />);
        expect(screen.getByRole('region', { name: 'Income statement' })).toBeTruthy();
        expect(screen.getByRole('region', { name: 'Balance sheet' })).toBeTruthy();
        expect(screen.getByRole('region', { name: 'Cash flow statement' })).toBeTruthy();
        expect(screen.getAllByText('2022-09-25 to 2023-09-30').length).toBeGreaterThan(0);
        expect(screen.getAllByText('53 week · 371 days').length).toBeGreaterThan(0);
        expect(screen.getAllByText('1/2 rows reported').length).toBe(2);
        expect(screen.getAllByText('USD 0.00').length).toBe(2);
        expect(screen.getAllByText('USD −450.25').length).toBe(2);
        expect(screen.getByText(/Coverage target · 5 annual periods/)).toBeTruthy();
        expect(screen.getAllByText(/Original filing could not be parsed/).length).toBeGreaterThan(0);
    });

    it('opens the exact cell selection and full original value in the existing inspector', () => {
        const selected = vi.fn();
        const model = report();
        const { rerender } = render(<AnnualStatementsTable report={model} onSelectEvidence={selected} />);
        fireEvent.click(screen.getByRole('button', { name: 'Inspect Revenue · FY2023' }));
        expect(selected).toHaveBeenCalledOnce();
        const evidence = model.evidence.find((item) => item.title === 'Revenue · FY2023');
        expect(selected).toHaveBeenCalledWith(evidence);
        if (!evidence) throw new Error('Missing fixture evidence');
        expect(evidence).toMatchObject({ value: '9007199254740993.125', contextId: 'context-revenueFY2023', selectionKind: 'original', artifactId: 'saved-statement' });
        expect(evidence.statementEvidence).toContain('synthetic-mapping-v1');
        rerender(<EvidenceInspector items={model.evidence} selected={evidence} onSelect={selected} />);
        expect(screen.getByLabelText('Original value · full precision').textContent).toBe('9007199254740993.125');
        expect(screen.getByText('context-revenueFY2023')).toBeTruthy();
        expect(screen.getByLabelText('Statement cell and candidate evidence').textContent).toBe(evidence.statementEvidence);
    });
});
