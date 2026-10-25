import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components/ui/empty-state';
import { Spinner } from '@/components/ui/spinner';

interface AgentLoadingStateProps {
    type: 'full' | 'block' | 'header';
    icon?: LucideIcon;
    title?: string;
    description?: string;
    status?: string;
    className?: string;
}

export const AgentLoadingState: React.FC<AgentLoadingStateProps> = ({
    type,
    icon: Icon,
    title,
    description,
    status,
    className = '',
}) => {
    if (type === 'header') {
        return (
            <span className={`inline-flex items-center gap-2 text-xs font-medium text-muted-foreground ${className}`} role="status">
                <Spinner label={title ?? 'Loading'} className="size-3 text-primary" />
                {title ?? 'Loading…'}
            </span>
        );
    }

    if (type === 'block') {
        return (
            <Alert className={`flex items-center gap-3 ${className}`} role="status">
                <Spinner label={title ?? description ?? 'Loading content'} className="text-primary" />
                <span className="text-muted-foreground">{title ?? description ?? 'Loading content…'}</span>
            </Alert>
        );
    }

    return (
        <EmptyState
            className={`min-h-[300px] px-6 py-10 ${className}`}
            icon={Icon ? <Icon aria-hidden="true" className="size-6" /> : <Spinner label={title ?? 'Processing'} className="size-6 text-primary" />}
            title={title ?? 'Processing…'}
            description={description}
            action={status ? <Badge variant="outline">Status: {status}</Badge> : undefined}
        />
    );
};
