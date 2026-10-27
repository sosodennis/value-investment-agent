'use client';

import Link from 'next/link';
import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowRight, LoaderCircle } from 'lucide-react';

import { useAuth } from '@/components/auth/AuthProvider';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { AuthApiError } from '@/lib/auth-api';

export default function LoginPage() {
    const router = useRouter();
    const { signIn } = useAuth();
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [isSubmitting, setIsSubmitting] = useState(false);

    async function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (isSubmitting) return;
        setIsSubmitting(true);
        setError(null);
        try {
            await signIn(email.trim(), password);
            router.replace('/workspace');
        } catch (cause) {
            setError(cause instanceof AuthApiError ? cause.message : 'Could not sign in.');
        } finally {
            setIsSubmitting(false);
        }
    }

    return (
        <main className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-background px-4 py-10 sm:px-6">
            <section className="w-full max-w-md border-y border-border bg-card px-5 py-8 sm:border sm:px-8" aria-labelledby="login-title">
                <p className="text-sm font-medium text-primary">Account access</p>
                <h1 id="login-title" className="mt-2 font-headline text-2xl font-semibold">Sign in</h1>
                <p className="mt-2 text-sm text-muted-foreground">Access your workspace and saved provider settings.</p>
                <form onSubmit={submit} className="mt-8 grid gap-5">
                    <Field label="Email" htmlFor="login-email">
                        <Input id="login-email" type="email" required autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} disabled={isSubmitting} />
                    </Field>
                    <Field label="Password" htmlFor="login-password">
                        <Input id="login-password" type="password" required autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={isSubmitting} />
                    </Field>
                    {error ? <Alert variant="destructive" role="alert"><AlertDescription>{error}</AlertDescription></Alert> : null}
                    <Button type="submit" className="w-full" disabled={isSubmitting}>
                        {isSubmitting ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <ArrowRight aria-hidden="true" />}
                        {isSubmitting ? 'Signing in...' : 'Sign in'}
                    </Button>
                </form>
                <p className="mt-6 text-center text-sm text-muted-foreground">New to FinanceAI? <Link className="font-medium text-primary underline-offset-4 hover:underline" href="/register">Create an account</Link></p>
            </section>
        </main>
    );
}
