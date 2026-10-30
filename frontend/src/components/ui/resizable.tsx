'use client';

import * as React from 'react';
import { GripVertical } from 'lucide-react';
import { cn } from '@/lib/cn';

type ResizableDirection = 'horizontal' | 'vertical';

type ResizableContextValue = {
    direction: ResizableDirection;
    groupRef: React.RefObject<HTMLDivElement | null>;
    sizes: number[];
    minSizes: number[];
    updateHandle: (index: number, deltaPixels: number) => void;
    adjustHandle: (index: number, deltaPercent: number) => void;
};

const ResizableContext = React.createContext<ResizableContextValue | null>(null);

function useResizableContext() {
    const context = React.useContext(ResizableContext);
    if (!context) throw new Error('Resizable panels must be rendered inside ResizableGroup.');
    return context;
}

export function ResizableGroup({
    className,
    direction = 'horizontal',
    defaultSizes = [50, 50],
    minSizes = defaultSizes.map(() => 12),
    children,
    ...props
}: React.HTMLAttributes<HTMLDivElement> & {
    direction?: ResizableDirection;
    defaultSizes?: number[];
    minSizes?: number[];
}) {
    const groupRef = React.useRef<HTMLDivElement | null>(null);
    const [sizes, setSizes] = React.useState(() => [...defaultSizes]);

    const updateHandle = React.useCallback((index: number, deltaPixels: number) => {
        const totalPixels = direction === 'horizontal'
            ? groupRef.current?.getBoundingClientRect().width ?? 0
            : groupRef.current?.getBoundingClientRect().height ?? 0;
        if (totalPixels <= 0) return;
        const deltaPercent = (deltaPixels / totalPixels) * 100;
        setSizes((current) => resizeAdjacentPanels(current, minSizes, index, deltaPercent));
    }, [direction, minSizes]);

    const adjustHandle = React.useCallback((index: number, deltaPercent: number) => {
        setSizes((current) => resizeAdjacentPanels(current, minSizes, index, deltaPercent));
    }, [minSizes]);

    const setGroupRef = React.useCallback((node: HTMLDivElement | null) => {
        groupRef.current = node;
    }, []);

    return (
        <ResizableContext.Provider value={{ direction, groupRef, sizes, minSizes, updateHandle, adjustHandle }}>
            <div
                ref={setGroupRef}
                data-resizable-group=""
                className={cn(
                    'flex min-h-0 min-w-0 overflow-hidden',
                    direction === 'horizontal' ? 'flex-row' : 'flex-col',
                    className,
                )}
                {...props}
            >
                {children}
            </div>
        </ResizableContext.Provider>
    );
}

export function ResizablePanel({
    className,
    index,
    children,
    ...props
}: React.HTMLAttributes<HTMLDivElement> & { index: number }) {
    const { direction, sizes } = useResizableContext();
    const size = sizes[index] ?? 0;
    return (
        <div
            data-resizable-panel={index}
            className={cn('min-h-0 min-w-0 overflow-auto', direction === 'horizontal' ? 'h-full' : 'w-full', className)}
            style={{ flex: `${size} 1 0%` }}
            {...props}
        >
            {children}
        </div>
    );
}

export function ResizableHandle({
    className,
    index,
    withHandle = true,
    ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { index: number; withHandle?: boolean }) {
    const { direction, sizes, minSizes, updateHandle, adjustHandle } = useResizableContext();
    const startPosition = React.useRef<number | null>(null);
    const orientation = direction === 'horizontal' ? 'vertical' : 'horizontal';

    function positionForEvent(event: React.PointerEvent<HTMLButtonElement>) {
        return direction === 'horizontal' ? event.clientX : event.clientY;
    }

    function handlePointerDown(event: React.PointerEvent<HTMLButtonElement>) {
        if (event.button !== 0) return;
        startPosition.current = positionForEvent(event);
        event.currentTarget.setPointerCapture(event.pointerId);
    }

    function handlePointerMove(event: React.PointerEvent<HTMLButtonElement>) {
        if (startPosition.current === null) return;
        const position = positionForEvent(event);
        updateHandle(index, position - startPosition.current);
        startPosition.current = position;
    }

    function handlePointerUp(event: React.PointerEvent<HTMLButtonElement>) {
        startPosition.current = null;
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId);
        }
    }

    function handleKeyDown(event: React.KeyboardEvent<HTMLButtonElement>) {
        const positive = direction === 'horizontal' ? event.key === 'ArrowRight' : event.key === 'ArrowDown';
        const negative = direction === 'horizontal' ? event.key === 'ArrowLeft' : event.key === 'ArrowUp';
        if (!positive && !negative) return;
        event.preventDefault();
        adjustHandle(index, positive ? 2 : -2);
    }

    return (
        <button
            type="button"
            role="separator"
            aria-orientation={orientation}
            aria-valuemin={minSizes[index] ?? 0}
            aria-valuemax={100 - (minSizes[index + 1] ?? 0)}
            aria-valuenow={Math.round(sizes[index] ?? 0)}
            aria-label="Resize workspace panel"
            data-resizable-handle={index}
            className={cn(
                'relative z-10 flex shrink-0 items-center justify-center border-border bg-border/60 text-muted-foreground transition-colors hover:bg-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
                direction === 'horizontal' ? 'w-px cursor-col-resize' : 'h-px cursor-row-resize',
                className,
            )}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
            onKeyDown={handleKeyDown}
            {...props}
        >
            {withHandle ? <GripVertical aria-hidden="true" className={cn('size-3', direction === 'vertical' && 'rotate-90')} /> : null}
        </button>
    );
}

function resizeAdjacentPanels(sizes: number[], minSizes: number[], index: number, deltaPercent: number) {
    const left = sizes[index] ?? 0;
    const right = sizes[index + 1] ?? 0;
    if (right <= 0) return sizes;
    const nextLeft = Math.min(
        Math.max(left + deltaPercent, minSizes[index] ?? 0),
        left + right - (minSizes[index + 1] ?? 0),
    );
    const next = [...sizes];
    next[index] = nextLeft;
    next[index + 1] = left + right - nextLeft;
    return next;
}
