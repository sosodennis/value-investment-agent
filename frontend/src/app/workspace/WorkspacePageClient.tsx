'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { WorkspacePage } from '@/features/workspace/workspace-page';
import { replaceStatementLocation } from '@/features/workspace/workspace-statement-location';
import { parseWorkspaceRouteIntent } from '@/features/workspace/workspace-route-intent';

export function WorkspacePageClient() {
    const searchParams = useSearchParams();
    const tickerParam = searchParams.get('ticker');
    const promptParam = searchParams.get('prompt');
    const [initialPrompt] = useState(() => promptParam?.trim() || null);
    const routeIntent = parseWorkspaceRouteIntent(searchParams);
    const workspaceIdentity = routeIntent.kind === 'statement-report'
        ? { kind: routeIntent.kind, threadId: routeIntent.threadId }
        : routeIntent;
    const initialTicker = tickerParam ? tickerParam.trim() : null;
    const shouldAutoStart = routeIntent.kind === 'new-analysis' && Boolean(initialPrompt || initialTicker);

    useEffect(() => {
        if (!initialPrompt || !promptParam) return;
        const url = new URL(window.location.href);
        url.searchParams.delete('prompt');
        replaceStatementLocation(url);
    }, [initialPrompt, promptParam]);

    return (
        <WorkspacePage
            key={JSON.stringify([workspaceIdentity, initialTicker, initialPrompt])}
            initialTicker={initialTicker}
            initialPrompt={initialPrompt}
            autoStart={shouldAutoStart}
            routeIntent={routeIntent}
        />
    );
}
