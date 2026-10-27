'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { WorkspacePage } from '@/features/workspace/workspace-page';
import { parseWorkspaceRouteIntent } from '@/features/workspace/workspace-route-intent';

export function WorkspacePageClient() {
    const searchParams = useSearchParams();
    const tickerParam = searchParams.get('ticker');
    const promptParam = searchParams.get('prompt');
    const [initialPrompt] = useState(() => promptParam?.trim() || null);
    const routeIntent = parseWorkspaceRouteIntent(searchParams);
    const initialTicker = tickerParam ? tickerParam.trim() : null;
    const shouldAutoStart = routeIntent.kind === 'new-analysis' && Boolean(initialPrompt || initialTicker);

    useEffect(() => {
        if (!initialPrompt || !promptParam) return;
        const url = new URL(window.location.href);
        url.searchParams.delete('prompt');
        const nextUrl = `${url.pathname}${url.search}${url.hash}`;
        window.history.replaceState(window.history.state, '', nextUrl);
    }, [initialPrompt, promptParam]);

    return (
        <WorkspacePage
            key={JSON.stringify([routeIntent, initialTicker, initialPrompt])}
            initialTicker={initialTicker}
            initialPrompt={initialPrompt}
            autoStart={shouldAutoStart}
            routeIntent={routeIntent}
        />
    );
}
