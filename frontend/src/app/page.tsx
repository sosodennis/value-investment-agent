'use client';

import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowRight, LoaderCircle, Search } from 'lucide-react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { HomeDashboard } from '@/features/home/home-dashboard';

export default function HomePage() {
    const router = useRouter();
    const [ticker, setTicker] = useState('');
    const [isNavigating, setIsNavigating] = useState(false);
    const [error, setError] = useState<string | null>(null);

    function startAnalysis(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        const query = ticker.trim();
        if (!query) {
            setError('Enter a company name or ticker symbol to start an analysis.');
            return;
        }
        setError(null);
        setIsNavigating(true);
        router.push(`/workspace?ticker=${encodeURIComponent(query)}`);
    }

    return (
        <main className="min-h-[calc(100vh-4rem)] bg-background px-4 py-8 sm:px-8 lg:px-10">
            <div className="mx-auto max-w-6xl">
                <section className="border-b border-border pb-8 sm:pb-10" aria-labelledby="home-title">
                    <p className="text-sm font-medium text-primary">Investment research</p>
                    <h1 id="home-title" className="mt-2 max-w-3xl font-headline text-3xl font-semibold sm:text-4xl">Start a company analysis</h1>
                    <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">Enter a company name or ticker to open the analysis workspace. The workflow resolves the company and asks you to confirm when ticker matches are ambiguous.</p>
                    <form onSubmit={startAnalysis} className="mt-7 grid max-w-2xl gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                        <Field label="Company name or ticker" htmlFor="analysis-ticker" description="For example, Apple or BRK.B.">
                            <div className="flex items-center gap-2 border-b border-input focus-within:border-ring">
                                <Search aria-hidden="true" className="ml-1 size-4 text-muted-foreground" />
                                <Input id="analysis-ticker" value={ticker} onChange={(event) => setTicker(event.target.value)} placeholder="Enter a company or ticker" autoComplete="off" disabled={isNavigating} className="border-0 focus-visible:border-0 focus-visible:shadow-none" />
                            </div>
                        </Field>
                        <Button type="submit" disabled={isNavigating} className="min-w-40">
                            {isNavigating ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <ArrowRight aria-hidden="true" />}
                            {isNavigating ? 'Opening workspace...' : 'Analyze company'}
                        </Button>
                    </form>
                    {error ? <Alert className="mt-4 max-w-2xl" variant="destructive" role="alert"><AlertDescription>{error}</AlertDescription></Alert> : null}
                </section>
                <HomeDashboard />
            </div>
        </main>
    );
}
