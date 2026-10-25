import * as React from 'react';
import { cn } from '@/lib/cn';
import { Label } from '@/components/ui/label';

export function Field({
    className,
    label,
    htmlFor,
    description,
    error,
    children,
}: {
    className?: string;
    label: React.ReactNode;
    htmlFor: string;
    description?: React.ReactNode;
    error?: React.ReactNode;
    children: React.ReactNode;
}) {
    return (
        <div className={cn('grid gap-2', className)}>
            <Label htmlFor={htmlFor}>{label}</Label>
            {children}
            {error ? (
                <p className="text-sm text-destructive" role="alert">
                    {error}
                </p>
            ) : description ? (
                <p className="text-sm text-muted-foreground">{description}</p>
            ) : null}
        </div>
    );
}
