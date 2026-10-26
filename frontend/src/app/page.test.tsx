import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import HomePage from './page';

vi.mock('@/features/home/home-dashboard', () => ({
    HomeDashboard: () => <section aria-label="Dashboard" />,
}));

const router = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => router }));

describe('home analysis entry', () => {
    beforeEach(() => vi.clearAllMocks());
    afterEach(cleanup);

    it('opens the analysis workspace with a trimmed ticker and pending feedback', () => {
        render(<HomePage />);
        const input = screen.getByLabelText('Company name or ticker');
        fireEvent.change(input, { target: { value: '  brk.b ' } });
        fireEvent.submit(input.closest('form')!);

        expect(router.push).toHaveBeenCalledWith('/workspace?ticker=brk.b');
        expect(screen.getByRole('button', { name: 'Opening workspace...' }).hasAttribute('disabled')).toBe(true);
    });

    it('shows validation feedback and does not navigate for an empty symbol', () => {
        render(<HomePage />);
        fireEvent.submit(screen.getByLabelText('Company name or ticker').closest('form')!);
        expect(screen.getByRole('alert').textContent).toContain('Enter a company name or ticker');
        expect(router.push).not.toHaveBeenCalled();
    });

    it('supports company names through the analysis workflow without inventing home data', () => {
        render(<HomePage />);
        fireEvent.change(screen.getByLabelText('Company name or ticker'), {
            target: { value: 'Apple Inc.' },
        });
        fireEvent.submit(screen.getByLabelText('Company name or ticker').closest('form')!);
        expect(router.push).toHaveBeenCalledWith('/workspace?ticker=Apple%20Inc.');
        expect(screen.getByRole('region', { name: 'Dashboard' })).toBeTruthy();
    });
});
