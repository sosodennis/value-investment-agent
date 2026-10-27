import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthApiError } from '@/lib/auth-api';
import RegisterPage from './register-page';

const auth = vi.hoisted(() => ({ signUp: vi.fn() }));
const router = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock('@/components/auth/AuthProvider', () => ({ useAuth: () => auth }));
vi.mock('next/navigation', () => ({ useRouter: () => router }));

describe('registration route', () => {
    beforeEach(() => vi.clearAllMocks());
    afterEach(cleanup);

    it('creates an account and redirects into the workspace', async () => {
        auth.signUp.mockResolvedValue({});
        render(<RegisterPage />);
        fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'analyst@example.com' } });
        fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password123' } });
        fireEvent.click(screen.getByRole('button', { name: 'Create account' }));

        await waitFor(() => expect(auth.signUp).toHaveBeenCalledWith('analyst@example.com', 'password123'));
        expect(router.replace).toHaveBeenCalledWith('/workspace');
    });

    it('shows request failures and prevents duplicate submissions while pending', async () => {
        let fail!: (error: unknown) => void;
        auth.signUp.mockReturnValue(new Promise((_, reject) => { fail = reject; }));
        render(<RegisterPage />);
        fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'analyst@example.com' } });
        fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password123' } });
        fireEvent.click(screen.getByRole('button', { name: 'Create account' }));
        const pendingButton = screen.getByRole('button', { name: 'Creating account...' });
        expect(pendingButton.hasAttribute('disabled')).toBe(true);
        fireEvent.click(pendingButton);
        expect(auth.signUp).toHaveBeenCalledOnce();
        fail(new AuthApiError('Email is already registered.', 409));
        expect((await screen.findByRole('alert')).textContent).toContain('Email is already registered.');
    });

    it('enforces email and password constraints before account creation', () => {
        render(<RegisterPage />);
        expect(screen.getByLabelText('Email').hasAttribute('required')).toBe(true);
        expect(screen.getByLabelText('Email').getAttribute('type')).toBe('email');
        expect(screen.getByLabelText('Password').getAttribute('minlength')).toBe('8');
        expect(auth.signUp).not.toHaveBeenCalled();
    });
});
