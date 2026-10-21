'use client';

import { Check, ChevronDown, Search } from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState } from 'react';

export type BeuiSelectOption = {
    value: string;
    label: string;
    description?: string | null;
};

type BeuiSelectProps = {
    value: string;
    options: BeuiSelectOption[];
    onValueChange: (value: string) => void;
    placeholder?: string;
    disabled?: boolean;
    'aria-label'?: string;
};

/**
 * Public beUI Select pattern: https://beui.dev/components/motion/select
 * The local implementation keeps the same accessible listbox interaction
 * while using this app's semantic surface tokens.
 */
export function BeuiSelect({
    value,
    options,
    onValueChange,
    placeholder = 'Select a model',
    disabled = false,
    'aria-label': ariaLabel,
}: BeuiSelectProps) {
    const rootRef = useRef<HTMLDivElement>(null);
    const listRef = useRef<HTMLDivElement>(null);
    const searchRef = useRef<HTMLInputElement>(null);
    const listId = useId();
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState('');
    const [activeIndex, setActiveIndex] = useState(0);
    const selected = options.find((option) => option.value === value);
    const filtered = useMemo(() => {
        const normalized = query.trim().toLowerCase();
        if (!normalized) return options;
        return options.filter((option) =>
            `${option.label} ${option.value} ${option.description ?? ''}`
                .toLowerCase()
                .includes(normalized),
        );
    }, [options, query]);

    useEffect(() => {
        if (!open) return;
        const closeOnPointer = (event: PointerEvent) => {
            const target = event.target;
            if (!(target instanceof Node) || !rootRef.current?.contains(target)) setOpen(false);
        };
        const closeOnKey = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setOpen(false);
                return;
            }
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                setActiveIndex((current) => {
                    const delta = event.key === 'ArrowDown' ? 1 : -1;
                    return filtered.length === 0
                        ? 0
                        : (current + delta + filtered.length) % filtered.length;
                });
            }
            if (event.key === 'Enter' && filtered[activeIndex]) {
                event.preventDefault();
                onValueChange(filtered[activeIndex].value);
                setOpen(false);
            }
        };
        window.addEventListener('pointerdown', closeOnPointer);
        window.addEventListener('keydown', closeOnKey);
        searchRef.current?.focus();
        return () => {
            window.removeEventListener('pointerdown', closeOnPointer);
            window.removeEventListener('keydown', closeOnKey);
        };
    }, [activeIndex, filtered, onValueChange, open]);

    return (
        <div ref={rootRef} className="relative">
            <button
                type="button"
                aria-label={ariaLabel}
                aria-haspopup="listbox"
                aria-expanded={open}
                aria-controls={listId}
                disabled={disabled}
                onClick={() => {
                    setActiveIndex(Math.max(0, filtered.findIndex((option) => option.value === value)));
                    setOpen((current) => !current);
                }}
                className="flex min-h-11 w-full items-center justify-between gap-3 rounded border border-outline-variant bg-surface px-3 text-left text-sm text-on-surface outline-none transition hover:border-primary-container focus-visible:ring-2 focus-visible:ring-primary-container/40 disabled:cursor-not-allowed disabled:opacity-50"
            >
                <span className={selected ? 'truncate' : 'text-on-surface-variant'}>
                    {selected?.label ?? placeholder}
                </span>
                <ChevronDown
                    size={16}
                    aria-hidden
                    className={`shrink-0 text-on-surface-variant transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
                />
            </button>
            {open && (
                <div
                    id={listId}
                    role="listbox"
                    aria-label={ariaLabel ?? 'Options'}
                    ref={listRef}
                    className="absolute z-30 mt-2 w-full min-w-[18rem] origin-top rounded border border-outline-variant bg-surface-container-high p-2 shadow-2xl transition duration-150 motion-reduce:transition-none"
                >
                    <div className="flex items-center gap-2 border-b border-outline-variant/60 px-2 pb-2">
                        <Search size={14} className="shrink-0 text-on-surface-variant" aria-hidden />
                        <input
                            ref={searchRef}
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                            placeholder="Search free models"
                            className="min-w-0 flex-1 bg-transparent py-1 text-sm text-on-surface outline-none placeholder:text-on-surface-variant"
                            aria-label="Search models"
                        />
                    </div>
                    <div className="mt-2 max-h-64 overflow-y-auto" tabIndex={-1}>
                        {filtered.length === 0 ? (
                            <p className="px-2 py-3 text-sm text-on-surface-variant">No matching models.</p>
                        ) : (
                            filtered.map((option, index) => (
                                <button
                                    key={option.value}
                                    type="button"
                                    role="option"
                                    aria-selected={option.value === value}
                                    onMouseEnter={() => setActiveIndex(index)}
                                    onClick={() => {
                                        onValueChange(option.value);
                                        setOpen(false);
                                    }}
                                    className={`flex w-full items-start gap-3 rounded px-2 py-2 text-left transition-colors motion-reduce:transition-none ${index === activeIndex ? 'bg-primary-container/10 text-on-surface' : 'text-on-surface-variant hover:bg-surface-container-highest'}`}
                                >
                                    <span className="mt-0.5 w-4 shrink-0 text-primary-container">
                                        {option.value === value ? <Check size={14} aria-hidden /> : null}
                                    </span>
                                    <span className="min-w-0">
                                        <span className="block truncate text-sm font-medium">{option.label}</span>
                                        <span className="mt-0.5 block truncate font-mono text-[10px] text-on-surface-variant">{option.value}</span>
                                    </span>
                                </button>
                            ))
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
