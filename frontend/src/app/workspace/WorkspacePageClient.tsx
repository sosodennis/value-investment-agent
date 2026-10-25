'use client';

import { useSearchParams } from 'next/navigation';
import { WorkspacePage } from '@/features/workspace/workspace-page';

export function WorkspacePageClient() {
    const searchParams = useSearchParams();
    const tickerParam = searchParams.get('ticker');
    const initialTicker = tickerParam ? tickerParam.trim() : null;
    const shouldAutoStart = Boolean(initialTicker);

    return (
        <WorkspacePage
            initialTicker={initialTicker}
            autoStart={shouldAutoStart}
        />
    );
}
