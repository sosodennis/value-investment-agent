import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import HomePage from './page';

const router = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => router }));

describe('home analysis entry', () => {
    beforeEach(() => vi.clearAllMocks());
    afterEach(cleanup);

    it('opens the analysis workspace with a normalized ticker and pending feedback', () => {
        render(<HomePage />);
        const input = screen.getByLabelText('Ticker symbol');
        fireEvent.change(input, { target: { value: '  brk.b ' } });
        fireEvent.submit(input.closest('form')!);

        expect(router.push).toHaveBeenCalledWith('/workspace?ticker=BRK.B');
        expect(screen.getByRole('button', { name: 'Opening workspace...' }).hasAttribute('disabled')).toBe(true);
    });

    it('shows validation feedback and does not navigate for an empty symbol', () => {
        render(<HomePage />);
        fireEvent.submit(screen.getByLabelText('Ticker symbol').closest('form')!);
        expect(screen.getByRole('alert').textContent).toContain('Enter a ticker symbol');
        expect(router.push).not.toHaveBeenCalled();
    });

    it('does not present fabricated market activity or a healthy status', () => {
        render(<HomePage />);
        expect(screen.getByText('A market data feed is not connected to this view.')).toBeTruthy();
        expect(screen.getByText('Recent analysis history is not available from the current API.')).toBeTruthy();
        expect(screen.queryByText(/Agent Online|healthy/i)).toBeNull();
    });
});
