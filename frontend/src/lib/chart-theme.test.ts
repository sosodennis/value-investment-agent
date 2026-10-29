import { describe, expect, it } from 'vitest';
import {
    chartColorCssVariable,
    parseChartTheme,
    resolveChartColor,
} from './chart-theme';

const tokenNames = [
    '--chart-axis',
    '--chart-axis-strong',
    '--chart-axis-border',
    '--chart-grid',
    '--chart-grid-soft',
    '--chart-series-primary',
    '--chart-series-secondary',
    '--chart-series-tertiary',
    '--chart-series-quaternary',
    '--chart-series-quinary',
    '--chart-series-up',
    '--chart-series-up-muted',
    '--chart-series-down',
    '--chart-series-down-muted',
    '--chart-series-warning',
    '--chart-series-neutral',
    '--chart-series-neutral-muted',
    '--chart-overlay-band',
    '--chart-overlay-band-soft',
    '--chart-tooltip-background',
    '--chart-tooltip-foreground',
    '--chart-tooltip-border',
    '--chart-tooltip-muted',
];

const createTheme = (omitToken?: string) => {
    const tokenValues = new Map(tokenNames.map((token, index) => [token, `token-${index}`]));
    const resolvedValues = new Map(tokenNames.map((token, index) => [token, `rgb(${index}, ${index}, ${index})`]));
    return parseChartTheme({
        readToken: (token) => token === omitToken ? '' : tokenValues.get(token) ?? '',
        resolveColor: (token) => resolvedValues.get(token) ?? '',
        fontFamily: 'var(--font-inter)',
    });
};

describe('chart theme roles', () => {
    it('parses all roles and resolves a typed role to its concrete CSS color', () => {
        const theme = createTheme();

        if (!theme) throw new Error('Expected all configured chart tokens to parse.');
        expect(resolveChartColor(theme, 'seriesUp')).toBe('rgb(10, 10, 10)');
        expect(resolveChartColor(theme, 'tooltipBackground')).toBe('rgb(19, 19, 19)');
        expect(theme.fontFamily).toBe('var(--font-inter)');
    });

    it('rejects a theme with an unavailable token or resolved color', () => {
        expect(createTheme('--chart-tooltip-muted')).toBeNull();
        const missingColor = parseChartTheme({
            readToken: (token) => token,
            resolveColor: (token) => token === '--chart-tooltip-muted' ? '' : '#123456',
            fontFamily: 'var(--font-inter)',
        });
        expect(missingColor).toBeNull();
    });

    it('keeps role to CSS variable mapping closed', () => {
        expect(chartColorCssVariable('seriesDown')).toBe('var(--chart-series-down)');
    });
});
