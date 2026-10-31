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

export default function RegisterPage() {
    const router = useRouter();
    const { signUp } = useAuth();
    const [email, setEmail] = useState('');
    const [displayName, setDisplayName] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [isSubmitting, setIsSubmitting] = useState(false);

    async function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (isSubmitting) return;
        setIsSubmitting(true);
        setError(null);
        try {
            await signUp(email.trim(), displayName.trim(), password);
            router.replace('/workspace');
        } catch (cause) {
            setError(cause instanceof AuthApiError ? cause.message : 'Could not create the account.');
        } finally {
            setIsSubmitting(false);
        }
    }

    return (
        <main className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-background px-4 py-10 sm:px-6">
            <section className="w-full max-w-md border-y border-border bg-card px-5 py-8 sm:border sm:px-8" aria-labelledby="register-title">
                <p className="text-sm font-medium text-primary">Account access</p>
                <h1 id="register-title" className="mt-2 font-headline text-2xl font-semibold">Create your account</h1>
                <p className="mt-2 text-sm text-muted-foreground">Your workspace and provider settings are scoped to your account.</p>
                <form onSubmit={submit} className="mt-8 grid gap-5">
                    <Field label="Display name" htmlFor="register-display-name">
                        <Input id="register-display-name" type="text" required maxLength={80} autoComplete="name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} disabled={isSubmitting} />
                    </Field>
                    <Field label="Email" htmlFor="register-email">
                        <Input id="register-email" type="email" required autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} disabled={isSubmitting} />
                    </Field>
                    <Field label="Password" htmlFor="register-password" description="Use at least 8 characters.">
                        <Input id="register-password" type="password" required minLength={8} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={isSubmitting} />
                    </Field>
                    {error ? <Alert variant="destructive" role="alert"><AlertDescription>{error}</AlertDescription></Alert> : null}
                    <Button type="submit" className="w-full" disabled={isSubmitting}>
                        {isSubmitting ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <ArrowRight aria-hidden="true" />}
                        {isSubmitting ? 'Creating account...' : 'Create account'}
                    </Button>
                </form>
                <p className="mt-6 text-center text-sm text-muted-foreground">Already have an account? <Link className="font-medium text-primary underline-offset-4 hover:underline" href="/login">Sign in</Link></p>
            </section>
        </main>
    );
}
