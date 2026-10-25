import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthApiError } from '@/lib/auth-api';
import LoginPage from './page';

const auth = vi.hoisted(() => ({ signIn: vi.fn() }));
const router = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock('@/components/auth/AuthProvider', () => ({ useAuth: () => auth }));
vi.mock('next/navigation', () => ({ useRouter: () => router }));

describe('login route', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    afterEach(cleanup);

    it('submits with the session API and redirects into the workspace', async () => {
        auth.signIn.mockResolvedValue({});
        render(<LoginPage />);
        fireEvent.change(screen.getByLabelText('Email'), { target: { value: ' analyst@example.com ' } });
        fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password123' } });
        fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

        await waitFor(() => expect(auth.signIn).toHaveBeenCalledWith('analyst@example.com', 'password123'));
        expect(router.replace).toHaveBeenCalledWith('/workspace');
    });

    it('shows request errors and disables duplicate submissions while pending', async () => {
        let finish!: (value: unknown) => void;
        auth.signIn.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
        render(<LoginPage />);
        fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'analyst@example.com' } });
        fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password123' } });
        fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
        const pendingButton = screen.getByRole('button', { name: 'Signing in...' });
        expect(pendingButton.hasAttribute('disabled')).toBe(true);
        fireEvent.click(pendingButton);
        expect(auth.signIn).toHaveBeenCalledOnce();
        finish(Promise.reject(new AuthApiError('Invalid credentials.', 401)));
        expect((await screen.findByRole('alert')).textContent).toContain('Invalid credentials.');
    });

    it('requires a valid email and password before submission', () => {
        render(<LoginPage />);
        const email = screen.getByLabelText('Email');
        const password = screen.getByLabelText('Password');
        expect(email.hasAttribute('required')).toBe(true);
        expect(password.hasAttribute('required')).toBe(true);
        expect(email.getAttribute('type')).toBe('email');
        expect(auth.signIn).not.toHaveBeenCalled();
    });
});
