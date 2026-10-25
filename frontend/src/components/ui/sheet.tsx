'use client';

import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '@/lib/cn';
import { DialogOverlay, DialogPortal } from '@/components/ui/dialog';

export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetClose = DialogPrimitive.Close;

type SheetSide = 'left' | 'right' | 'top' | 'bottom';

const sideClasses: Record<SheetSide, string> = {
    left: 'inset-y-0 left-0 h-full w-[min(20rem,calc(100vw-3rem))] border-r data-[state=closed]:-translate-x-full data-[state=open]:translate-x-0',
    right: 'inset-y-0 right-0 h-full w-[min(20rem,calc(100vw-3rem))] border-l data-[state=closed]:translate-x-full data-[state=open]:translate-x-0',
    top: 'inset-x-0 top-0 max-h-[85vh] w-full border-b data-[state=closed]:-translate-y-full data-[state=open]:translate-y-0',
    bottom: 'inset-x-0 bottom-0 max-h-[85vh] w-full border-t data-[state=closed]:translate-y-full data-[state=open]:translate-y-0',
};

export const SheetContent = React.forwardRef<
    React.ElementRef<typeof DialogPrimitive.Content>,
    React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
        side?: SheetSide;
        showCloseButton?: boolean;
    }
>(({ className, children, side = 'right', showCloseButton = true, ...props }, ref) => (
    <DialogPortal>
        <DialogOverlay />
        <DialogPrimitive.Content
            ref={ref}
            className={cn('fixed z-50 flex flex-col gap-4 overflow-y-auto bg-popover p-6 text-popover-foreground shadow-[0_24px_48px_-12px_rgba(0,0,0,0.5)] transition-transform duration-200 focus:outline-none', sideClasses[side], className)}
            {...props}
        >
            {children}
            {showCloseButton ? (
                <DialogPrimitive.Close
                    className="absolute right-4 top-4 inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label="Close navigation"
                >
                    <X aria-hidden="true" className="size-4" />
                </DialogPrimitive.Close>
            ) : null}
        </DialogPrimitive.Content>
    </DialogPortal>
));
SheetContent.displayName = DialogPrimitive.Content.displayName;

export function SheetHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
    return <div className={cn('flex flex-col gap-2 text-left', className)} {...props} />;
}

export const SheetTitle = DialogPrimitive.Title;
export const SheetDescription = DialogPrimitive.Description;
