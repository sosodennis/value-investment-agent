'use client';

import Link from 'next/link';
import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AuthApiError } from '@/lib/auth-api';
import { useAuth } from '@/components/auth/AuthProvider';

export default function RegisterPage() {
    const router = useRouter();
    const { signUp } = useAuth();
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

    async function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        setBusy(true);
        setError(null);
        try {
            await signUp(email.trim(), password);
            router.replace('/workspace');
        } catch (cause) {
            setError(cause instanceof AuthApiError ? cause.message : 'Could not create the account.');
        } finally {
            setBusy(false);
        }
    }

    return (
        <main className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-surface px-6 py-12">
            <form onSubmit={submit} className="w-full max-w-md rounded-lg border border-outline-variant/50 bg-surface-container-low p-7">
                <p className="text-label mb-3">FinanceAI Lab</p>
                <h1 className="font-headline text-2xl">Create your account</h1>
                <p className="mt-2 text-sm text-on-surface-variant">Your analyses and OpenRouter keys stay isolated to this account.</p>
                <label className="text-label mt-7 block" htmlFor="register-email">Email</label>
                <input id="register-email" type="email" required autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} className="mt-2 w-full rounded border border-outline-variant bg-surface px-3 py-2 text-sm" />
                <label className="text-label mt-5 block" htmlFor="register-password">Password</label>
                <input id="register-password" type="password" required minLength={8} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 w-full rounded border border-outline-variant bg-surface px-3 py-2 text-sm" />
                {error ? <p role="alert" className="mt-4 text-sm text-error">{error}</p> : null}
                <button type="submit" disabled={busy} className="mt-6 w-full rounded bg-primary-container px-4 py-2.5 text-sm font-semibold text-on-primary disabled:opacity-50">{busy ? 'Creating account...' : 'Create account'}</button>
                <p className="mt-5 text-center text-sm text-on-surface-variant">Already registered? <Link className="text-primary-container underline" href="/login">Sign in</Link></p>
            </form>
        </main>
    );
}
