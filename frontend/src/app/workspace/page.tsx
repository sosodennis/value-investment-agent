import { Suspense } from 'react';
import { WorkspacePageClient } from './WorkspacePageClient';

export default function WorkspacePage() {
    return (
        <Suspense fallback={<div className="min-h-screen w-full bg-slate-950" />}>
            <WorkspacePageClient />
        </Suspense>
    );
}
