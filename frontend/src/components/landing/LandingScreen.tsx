'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { LandingHero } from './LandingHero';
import { LandingSearch } from './LandingSearch';
import { TrendingTickers, TrendingTicker } from './TrendingTickers';
import { RecentAnalysis, RecentAnalysisItem } from './RecentAnalysis';

const TRENDING_TICKERS: TrendingTicker[] = [
    {
        symbol: 'NVDA',
        name: 'NVIDIA Corp.',
        price: '$942.89',
        change: '+2.45%',
        trend: 'up',
    },
    {
        symbol: 'TSLA',
        name: 'Tesla, Inc.',
        price: '$171.05',
        change: '-1.12%',
        trend: 'down',
    },
    {
        symbol: 'AAPL',
        name: 'Apple Inc.',
        price: '$182.52',
        change: '0.00%',
        trend: 'flat',
    },
];

const RECENT_ANALYSIS: RecentAnalysisItem[] = [
    {
        title: 'MSFT Deep Dive',
        summary: 'AI workloads driving cloud revenue expansion beyond estimates.',
        time: 'Analyzed 14m ago',
        icon: 'stats',
    },
    {
        title: 'Market Sentiment Hub',
        summary: 'Fear/Greed index shifting toward aggressive accumulation.',
        time: 'Analyzed 2h ago',
        icon: 'insights',
    },
];

export function LandingScreen() {
    const router = useRouter();
    const [ticker, setTicker] = useState('');

    const handleAnalyze = () => {
        const normalized = ticker.trim().toUpperCase();
        if (!normalized) return;
        router.push(`/workspace?ticker=${encodeURIComponent(normalized)}`);
    };

    return (
        <div className="min-h-[calc(100vh-4rem)] bg-surface text-on-surface font-body">
            <main className="relative min-h-[calc(100vh-4rem)] flex flex-col items-center px-4 pt-8 pb-16 hero-gradient">
                <div className="absolute top-8 right-8 flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface-container-low border border-outline-variant/20 shadow-lg">
                    <span className="relative flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-secondary opacity-75" />
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-secondary" />
                    </span>
                    <span className="text-[10px] uppercase tracking-widest font-bold text-secondary">
                        Agent Online
                    </span>
                </div>

                <div className="w-full max-w-3xl text-center space-y-10">
                    <LandingHero />
                    <LandingSearch
                        ticker={ticker}
                        onTickerChange={setTicker}
                        onAnalyze={handleAnalyze}
                    />
                    <TrendingTickers
                        tickers={TRENDING_TICKERS}
                        onSelectTicker={setTicker}
                    />
                    <RecentAnalysis items={RECENT_ANALYSIS} />
                </div>
            </main>

            <div className="fixed inset-0 pointer-events-none -z-10 overflow-hidden">
                <div className="absolute -top-[10%] -left-[10%] w-[40%] h-[40%] bg-primary-container/5 rounded-full blur-[120px]" />
                <div className="absolute bottom-0 right-0 w-full h-[30%] bg-gradient-to-t from-surface-container-lowest to-transparent" />
            </div>
        </div>
    );
}
