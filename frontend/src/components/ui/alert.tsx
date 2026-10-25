import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/cn';

const alertVariants = cva('relative w-full rounded-md border p-4 text-sm', {
    variants: {
        variant: {
            default: 'border-border bg-card text-card-foreground',
            success: 'border-success/30 bg-success/10 text-success',
            warning: 'border-warning/30 bg-warning/10 text-warning',
            destructive: 'border-destructive/30 bg-destructive/10 text-destructive',
        },
    },
    defaultVariants: {
        variant: 'default',
    },
});

export type AlertProps = React.HTMLAttributes<HTMLDivElement> &
    VariantProps<typeof alertVariants> & {
        role?: 'alert' | 'status';
    };

export function Alert({ className, variant, role = 'status', ...props }: AlertProps) {
    return (
        <div
            role={role}
            className={cn(alertVariants({ variant }), className)}
            {...props}
        />
    );
}

export function AlertTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
    return <h3 className={cn('mb-1 font-semibold', className)} {...props} />;
}

export function AlertDescription({
    className,
    ...props
}: React.HTMLAttributes<HTMLParagraphElement>) {
    return <p className={cn('text-sm opacity-90', className)} {...props} />;
}
