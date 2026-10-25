import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Combobox } from './combobox';

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    Reflect.deleteProperty(Element.prototype, 'scrollIntoView');
});

describe('Combobox', () => {
    it('filters options and reports the selected value', async () => {
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe() {}
                unobserve() {}
                disconnect() {}
            },
        );
        Object.defineProperty(Element.prototype, 'scrollIntoView', {
            configurable: true,
            value: vi.fn(),
        });
        const onValueChange = vi.fn();

        render(
            <Combobox
                ariaLabel="Choose a company"
                options={[
                    { value: 'AAPL', label: 'Apple Inc.', keywords: ['NASDAQ'] },
                    { value: 'MSFT', label: 'Microsoft Corporation', keywords: ['NASDAQ'] },
                ]}
                onValueChange={onValueChange}
            />,
        );

        fireEvent.click(screen.getByRole('combobox', { name: 'Choose a company' }));

        const search = await screen.findByPlaceholderText('Search options...');
        fireEvent.change(search, { target: { value: 'Microsoft' } });
        fireEvent.click(await screen.findByRole('option', { name: /Microsoft Corporation/ }));

        expect(onValueChange).toHaveBeenCalledWith('MSFT');
        await waitFor(() => expect(screen.getByRole('combobox', { name: 'Choose a company' }).textContent).toContain('Microsoft Corporation'));
    });
});
