'use client';

import { useSearchParams } from 'next/navigation';
import { AnalysisWorkspace } from '@/components/workspace/AnalysisWorkspace';

export function WorkspacePageClient() {
    const searchParams = useSearchParams();
    const tickerParam = searchParams.get('ticker');
    const initialTicker = tickerParam ? tickerParam.trim() : null;
    const shouldAutoStart = Boolean(initialTicker);

    return (
        <AnalysisWorkspace
            initialTicker={initialTicker}
            autoStart={shouldAutoStart}
        />
    );
}
