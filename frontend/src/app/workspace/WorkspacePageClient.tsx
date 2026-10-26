'use client';

import { useSearchParams } from 'next/navigation';
import { WorkspacePage } from '@/features/workspace/workspace-page';
import { parseWorkspaceRouteIntent } from '@/features/workspace/workspace-route-intent';

export function WorkspacePageClient() {
    const searchParams = useSearchParams();
    const tickerParam = searchParams.get('ticker');
    const routeIntent = parseWorkspaceRouteIntent(searchParams);
    const initialTicker = tickerParam ? tickerParam.trim() : null;
    const shouldAutoStart = routeIntent.kind === 'new-analysis' && Boolean(initialTicker);

    return (
        <WorkspacePage
            key={JSON.stringify([routeIntent, initialTicker])}
            initialTicker={initialTicker}
            autoStart={shouldAutoStart}
            routeIntent={routeIntent}
        />
    );
}
