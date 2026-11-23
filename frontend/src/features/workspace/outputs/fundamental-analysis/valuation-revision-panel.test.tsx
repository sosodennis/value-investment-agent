import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ValuationRevisionPanel } from './valuation-revision-panel';
import { deferred, forwardReview, revisionContext } from './valuation-revision.test-fixtures';

function openResearch() {
    fireEvent.click(screen.getByText('Research external evidence (optional)'));
}

describe('valuation revision panel', () => {
    afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
    it('keeps manual edits available when the service cannot apply research to this preparation', () => {
        render(<ValuationRevisionPanel context={{ ...revisionContext(), canApplyResearch: false }} isPending={false} onRecalculate={vi.fn()} />);
        expect(screen.queryByText('Research external evidence (optional)')).toBeNull();
        screen.getByText(/Research cannot be applied to this report/);
        expect(screen.getByRole('button', { name: 'Recalculate' }).hasAttribute('disabled')).toBe(false);
    });
    it('validates blank fields and submits exact zero with one explicit Recalculate action', async () => {
        const pending = deferred<void>();
        const recalculate = vi.fn(() => pending.promise);
        const context = revisionContext();
        render(<ValuationRevisionPanel context={context} isPending={false} onRecalculate={recalculate} />);
        fireEvent.change(screen.getByLabelText('Terminal growth (%)'), { target: { value: '' } });
        fireEvent.click(screen.getByRole('button', { name: 'Recalculate' }));
        screen.getByText('Enter a finite decimal percentage.');
        screen.getByText('Explain why you are changing this assumption.');
        expect(recalculate).not.toHaveBeenCalled();
        fireEvent.change(screen.getByLabelText('Terminal growth (%)'), { target: { value: '0' } });
        fireEvent.change(screen.getByLabelText('Reason for change'), { target: { value: 'No perpetual growth.' } });
        const button = screen.getByRole('button', { name: 'Recalculate' });
        fireEvent.click(button);
        fireEvent.click(button);
        expect(recalculate).toHaveBeenCalledTimes(1);
        expect(recalculate).toHaveBeenCalledWith({ source: context.source, path: 'assumptions.terminal_growth', value: '0', reason: 'No perpetual growth.' }, 'EXAMPLE');
        expect(screen.getByRole('button', { name: 'Recalculating…' }).hasAttribute('disabled')).toBe(true);
        await act(async () => pending.resolve());
        expect(screen.queryByText(/recalculated successfully/i)).toBeNull();
    });
    it('retains the draft and permits an explicit retry after a controlled refusal', async () => {
        const recalculate = vi.fn().mockRejectedValueOnce(new Error('Terminal growth must be below the service discount rate.')).mockResolvedValueOnce(undefined);
        render(<ValuationRevisionPanel context={revisionContext()} isPending={false} onRecalculate={recalculate} />);
        fireEvent.change(screen.getByLabelText('Terminal growth (%)'), { target: { value: '-1.234567890123456789' } });
        fireEvent.change(screen.getByLabelText('Reason for change'), { target: { value: 'Lower growth expectation.' } });
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Recalculate' })));
        screen.getByText('Terminal growth must be below the service discount rate.');
        expect(screen.getByLabelText('Terminal growth (%)').getAttribute('value')).toBe('-1.234567890123456789');
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Recalculate' })));
        expect(recalculate).toHaveBeenCalledTimes(2);
        expect(recalculate.mock.calls[1]?.[0].value).toBe('-0.01234567890123456789');
    });
    it('researches only on opt-in, stages a reviewed claim, then recalculates with its citation', async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ result: forwardReview() }), { status: 200 }));
        vi.stubGlobal('fetch', fetchMock);
        const recalculate = vi.fn().mockResolvedValue(undefined);
        const context = revisionContext();
        render(<ValuationRevisionPanel context={context} isPending={false} onRecalculate={recalculate} />);
        expect(fetchMock).not.toHaveBeenCalled();
        openResearch();
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Research external evidence' })));
        expect(recalculate).not.toHaveBeenCalled();
        expect(screen.getByLabelText('Terminal growth (%)').getAttribute('value')).toBe('2');
        screen.getByText('The published long-term growth outlook is three percent.');
        screen.getByText('License · approved · issuer-terms-v1');
        fireEvent.click(screen.getByRole('button', { name: 'Apply claim-1 to draft' }));
        expect(screen.getByLabelText('Terminal growth (%)').getAttribute('value')).toBe('3');
        expect(recalculate).not.toHaveBeenCalled();
        screen.getByText('Applied claim-1 to the draft. Recalculate to run the valuation.');
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Recalculate' })));
        expect(recalculate).toHaveBeenCalledWith(expect.objectContaining({ value: '0.03', source: context.source, forward_reference: expect.objectContaining({ claim_id: 'claim-1', source_content_hash: 'f'.repeat(64), license_reference: 'issuer-terms-v1' }), forward_review_ref: forwardReview().review_ref }), 'EXAMPLE');
        const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
        expect(body).toMatchObject({ opt_in: true, ticker: 'EXAMPLE', assumption_path: 'assumptions.terminal_growth', automatic_preparation_digest: context.source.preparation_digest });
        expect(body).not.toHaveProperty('preparation');
    });
    it('keeps research errors separate from the unchanged draft and recalculation', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Research provider unavailable.' }), { status: 503 })));
        const recalculate = vi.fn();
        render(<ValuationRevisionPanel context={revisionContext()} isPending={false} onRecalculate={recalculate} />);
        openResearch();
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Research external evidence' })));
        screen.getByText('Research provider unavailable.');
        expect(screen.getByLabelText('Terminal growth (%)').getAttribute('value')).toBe('2');
        expect(recalculate).not.toHaveBeenCalled();
        expect(screen.getByRole('button', { name: 'Recalculate' }).hasAttribute('disabled')).toBe(false);
    });
    it('aborts old research and ignores its late response after the source changes', async () => {
        const pending = deferred<Response>();
        const fetchMock = vi.fn<typeof fetch>(() => pending.promise);
        vi.stubGlobal('fetch', fetchMock);
        const recalculate = vi.fn();
        const first = revisionContext();
        const { rerender } = render(<ValuationRevisionPanel key={first.sourceKey} context={first} isPending={false} onRecalculate={recalculate} />);
        openResearch();
        fireEvent.click(screen.getByRole('button', { name: 'Research external evidence' }));
        expect(fetchMock).toHaveBeenCalledOnce();
        const next = revisionContext('run-2');
        rerender(<ValuationRevisionPanel key={next.sourceKey} context={next} isPending={false} onRecalculate={recalculate} />);
        expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
        await act(async () => pending.resolve(new Response(JSON.stringify({ result: forwardReview() }), { status: 200 })));
        expect(screen.queryByRole('button', { name: 'Apply claim-1 to draft' })).toBeNull();
        expect(screen.getByLabelText('Terminal growth (%)').getAttribute('value')).toBe('2');
    });
    it('ignores late recalculation errors after the source changes', async () => {
        const pending = deferred<void>();
        const recalculate = vi.fn(() => pending.promise);
        const first = revisionContext();
        const { rerender } = render(<ValuationRevisionPanel key={first.sourceKey} context={first} isPending={false} onRecalculate={recalculate} />);
        fireEvent.change(screen.getByLabelText('Reason for change'), { target: { value: 'Changed outlook.' } });
        fireEvent.click(screen.getByRole('button', { name: 'Recalculate' }));
        const next = revisionContext('run-2');
        rerender(<ValuationRevisionPanel key={next.sourceKey} context={next} isPending={false} onRecalculate={recalculate} />);
        await act(async () => pending.reject(new Error('Old request failed.')));
        expect(screen.queryByText('Old request failed.')).toBeNull();
        expect(screen.getByRole('button', { name: 'Recalculate' }).hasAttribute('disabled')).toBe(false);
    });
});
