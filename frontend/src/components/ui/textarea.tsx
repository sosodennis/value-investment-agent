import * as React from 'react';
import { cn } from '@/lib/cn';

export const Textarea = React.forwardRef<
    HTMLTextAreaElement,
    React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
    <textarea
        className={cn(
            'flex min-h-24 w-full resize-y rounded-none border-0 border-b border-input bg-transparent px-1 py-2 text-sm text-foreground ring-offset-background placeholder:text-muted-foreground focus-visible:border-b-2 focus-visible:border-ring focus-visible:outline-none focus-visible:ring-0 focus-visible:shadow-[0_4px_10px_-6px_var(--ring)] disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive',
            className,
        )}
        ref={ref}
        {...props}
    />
));
Textarea.displayName = 'Textarea';
