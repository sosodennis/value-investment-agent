'use client';

import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '@/lib/cn';

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogPortal = DialogPrimitive.Portal;
export const DialogClose = DialogPrimitive.Close;

export const DialogOverlay = React.forwardRef<
    React.ElementRef<typeof DialogPrimitive.Overlay>,
    React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
    <DialogPrimitive.Overlay
        ref={ref}
        className={cn('fixed inset-0 z-50 bg-background/80 backdrop-blur-sm transition-opacity duration-200 data-[state=open]:opacity-100 data-[state=closed]:opacity-0', className)}
        {...props}
    />
));
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;

export const DialogContent = React.forwardRef<
    React.ElementRef<typeof DialogPrimitive.Content>,
    React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
        showCloseButton?: boolean;
    }
>(({ className, children, showCloseButton = true, ...props }, ref) => (
    <DialogPortal>
        <DialogOverlay />
        <DialogPrimitive.Content
            ref={ref}
            className={cn('fixed left-1/2 top-1/2 z-50 grid w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 rounded-lg bg-popover p-6 text-popover-foreground shadow-[0_24px_48px_-12px_rgba(0,0,0,0.5)] focus:outline-none', className)}
            {...props}
        >
            {children}
            {showCloseButton ? (
                <DialogPrimitive.Close
                    className="absolute right-4 top-4 inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label="Close dialog"
                >
                    <X aria-hidden="true" className="size-4" />
                </DialogPrimitive.Close>
            ) : null}
        </DialogPrimitive.Content>
    </DialogPortal>
));
DialogContent.displayName = DialogPrimitive.Content.displayName;

export function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
    return <div className={cn('flex flex-col gap-2 text-left', className)} {...props} />;
}

export function DialogTitle({
    className,
    ...props
}: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>) {
    return (
        <DialogPrimitive.Title
            className={cn('text-lg font-semibold leading-none text-foreground', className)}
            {...props}
        />
    );
}

export function DialogDescription({
    className,
    ...props
}: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>) {
    return (
        <DialogPrimitive.Description
            className={cn('text-sm text-muted-foreground', className)}
            {...props}
        />
    );
}
