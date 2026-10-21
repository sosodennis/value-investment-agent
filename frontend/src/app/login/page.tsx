'use client';

import Link from 'next/link';
import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AuthApiError } from '@/lib/auth-api';
import { useAuth } from '@/components/auth/AuthProvider';

export default function LoginPage() {
    const router = useRouter();
    const { signIn } = useAuth();
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

    async function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        setBusy(true);
        setError(null);
        try {
            await signIn(email.trim(), password);
            router.replace('/workspace');
        } catch (cause) {
            setError(cause instanceof AuthApiError ? cause.message : 'Could not sign in.');
        } finally {
            setBusy(false);
        }
    }

    return (
        <main className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-surface px-6 py-12">
            <form onSubmit={submit} className="w-full max-w-md rounded-lg border border-outline-variant/50 bg-surface-container-low p-7">
                <p className="text-label mb-3">FinanceAI Lab</p>
                <h1 className="font-headline text-2xl">Sign in</h1>
                <p className="mt-2 text-sm text-on-surface-variant">Use your account to access analyses and personal provider keys.</p>
                <label className="text-label mt-7 block" htmlFor="login-email">Email</label>
                <input id="login-email" type="email" required autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} className="mt-2 w-full rounded border border-outline-variant bg-surface px-3 py-2 text-sm" />
                <label className="text-label mt-5 block" htmlFor="login-password">Password</label>
                <input id="login-password" type="password" required autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 w-full rounded border border-outline-variant bg-surface px-3 py-2 text-sm" />
                {error ? <p role="alert" className="mt-4 text-sm text-error">{error}</p> : null}
                <button type="submit" disabled={busy} className="mt-6 w-full rounded bg-primary-container px-4 py-2.5 text-sm font-semibold text-on-primary disabled:opacity-50">{busy ? 'Signing in...' : 'Sign in'}</button>
                <p className="mt-5 text-center text-sm text-on-surface-variant">No account? <Link className="text-primary-container underline" href="/register">Create one</Link></p>
            </form>
        </main>
    );
}
