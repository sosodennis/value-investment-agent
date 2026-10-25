'use client';

import * as React from 'react';
import { Check, ChevronsUpDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
    Command,
    CommandEmpty,
    CommandInput,
    CommandItem,
    CommandList,
} from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/cn';

export type ComboboxOption = {
    value: string;
    label: string;
    keywords?: string[];
    disabled?: boolean;
};

export type ComboboxProps = {
    options: readonly ComboboxOption[];
    ariaLabel: string;
    value?: string;
    defaultValue?: string;
    placeholder?: string;
    searchPlaceholder?: string;
    emptyMessage?: string;
    disabled?: boolean;
    className?: string;
    onValueChange?: (value: string) => void;
};

export function Combobox({
    options,
    ariaLabel,
    value,
    defaultValue = '',
    placeholder = 'Select an option',
    searchPlaceholder = 'Search options...',
    emptyMessage = 'No options found.',
    disabled = false,
    className,
    onValueChange,
}: ComboboxProps) {
    const [open, setOpen] = React.useState(false);
    const [internalValue, setInternalValue] = React.useState(defaultValue);
    const listId = React.useId();
    const selectedValue = value === undefined ? internalValue : value;
    const selectedOption = options.find((option) => option.value === selectedValue);

    function handleSelect(nextValue: string) {
        const valueToSet = selectedValue === nextValue ? '' : nextValue;
        if (value === undefined) setInternalValue(valueToSet);
        onValueChange?.(valueToSet);
        setOpen(false);
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                <Button
                    type="button"
                    variant="outline"
                    role="combobox"
                    aria-label={ariaLabel}
                    aria-expanded={open}
                    aria-controls={listId}
                    disabled={disabled}
                    className={cn('w-full justify-between font-normal', className)}
                >
                    <span className={cn('truncate', !selectedOption && 'text-muted-foreground')}>
                        {selectedOption?.label ?? placeholder}
                    </span>
                    <ChevronsUpDown aria-hidden="true" className="ml-2 size-4 shrink-0 opacity-50" />
                </Button>
            </PopoverTrigger>
            <PopoverContent
                align="start"
                className="w-[var(--radix-popover-trigger-width)] min-w-48 p-0"
                role="presentation"
            >
                <Command>
                    <CommandInput placeholder={searchPlaceholder} aria-label={searchPlaceholder} />
                    <CommandList id={listId}>
                        <CommandEmpty>{emptyMessage}</CommandEmpty>
                        {options.map((option) => (
                            <CommandItem
                                key={option.value}
                                value={option.label}
                                keywords={option.keywords}
                                disabled={option.disabled}
                                onSelect={() => handleSelect(option.value)}
                            >
                                <Check
                                    aria-hidden="true"
                                    className={cn(
                                        'size-4',
                                        selectedValue === option.value ? 'opacity-100' : 'opacity-0',
                                    )}
                                />
                                {option.label}
                            </CommandItem>
                        ))}
                    </CommandList>
                </Command>
            </PopoverContent>
        </Popover>
    );
}
