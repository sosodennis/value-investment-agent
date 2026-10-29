'use client';

import { useEffect, useState } from 'react';

const CHART_THEME_TOKENS = {
    axisText: '--chart-axis',
    axisTextStrong: '--chart-axis-strong',
    axisBorder: '--chart-axis-border',
    gridLine: '--chart-grid',
    gridLineSoft: '--chart-grid-soft',
    seriesPrimary: '--chart-series-primary',
    seriesSecondary: '--chart-series-secondary',
    seriesTertiary: '--chart-series-tertiary',
    seriesQuaternary: '--chart-series-quaternary',
    seriesQuinary: '--chart-series-quinary',
    seriesUp: '--chart-series-up',
    seriesUpMuted: '--chart-series-up-muted',
    seriesDown: '--chart-series-down',
    seriesDownMuted: '--chart-series-down-muted',
    seriesWarning: '--chart-series-warning',
    seriesNeutral: '--chart-series-neutral',
    seriesNeutralMuted: '--chart-series-neutral-muted',
    overlayBand: '--chart-overlay-band',
    overlayBandSoft: '--chart-overlay-band-soft',
    tooltipBackground: '--chart-tooltip-background',
    tooltipForeground: '--chart-tooltip-foreground',
    tooltipBorder: '--chart-tooltip-border',
    tooltipMuted: '--chart-tooltip-muted',
} as const;

export type ChartColorRole = keyof typeof CHART_THEME_TOKENS;
export type ChartValueColorRole = 'seriesUpMuted' | 'seriesDownMuted';

export type ChartTheme = Readonly<Record<ChartColorRole, string> & {
    fontFamily: string;
}>;

type IncompleteChartTheme = Readonly<Record<ChartColorRole, string | null>>;

export interface ChartThemeParserInput {
    readToken: (token: string) => string;
    resolveColor: (token: string) => string;
    fontFamily: string;
}

const hasCompleteColorSet = (
    colors: IncompleteChartTheme
): colors is Record<ChartColorRole, string> =>
    Object.values(colors).every((color) => color !== null);

export const parseChartTheme = ({
    readToken,
    resolveColor,
    fontFamily,
}: ChartThemeParserInput): ChartTheme | null => {
    const read = (role: ChartColorRole): string | null => {
        const token = CHART_THEME_TOKENS[role];
        if (!readToken(token).trim()) return null;
        const color = resolveColor(token).trim();
        return color.length > 0 ? color : null;
    };
    const colors = {
        axisText: read('axisText'),
        axisTextStrong: read('axisTextStrong'),
        axisBorder: read('axisBorder'),
        gridLine: read('gridLine'),
        gridLineSoft: read('gridLineSoft'),
        seriesPrimary: read('seriesPrimary'),
        seriesSecondary: read('seriesSecondary'),
        seriesTertiary: read('seriesTertiary'),
        seriesQuaternary: read('seriesQuaternary'),
        seriesQuinary: read('seriesQuinary'),
        seriesUp: read('seriesUp'),
        seriesUpMuted: read('seriesUpMuted'),
        seriesDown: read('seriesDown'),
        seriesDownMuted: read('seriesDownMuted'),
        seriesWarning: read('seriesWarning'),
        seriesNeutral: read('seriesNeutral'),
        seriesNeutralMuted: read('seriesNeutralMuted'),
        overlayBand: read('overlayBand'),
        overlayBandSoft: read('overlayBandSoft'),
        tooltipBackground: read('tooltipBackground'),
        tooltipForeground: read('tooltipForeground'),
        tooltipBorder: read('tooltipBorder'),
        tooltipMuted: read('tooltipMuted'),
    } satisfies IncompleteChartTheme;

    if (!hasCompleteColorSet(colors) || !fontFamily.trim()) return null;
    return { ...colors, fontFamily: fontFamily.trim() };
};

export const readChartTheme = (element?: HTMLElement | null): ChartTheme | null => {
    if (typeof window === 'undefined' || typeof document === 'undefined') return null;

    const themeElement = element ?? document.body ?? document.documentElement;
    const style = window.getComputedStyle(themeElement);
    const probe = document.createElement('span');
    themeElement.appendChild(probe);

    const theme = parseChartTheme({
        readToken: (token) => style.getPropertyValue(token),
        resolveColor: (token) => {
            probe.style.color = `var(${token})`;
            return window.getComputedStyle(probe).color;
        },
        fontFamily: style.getPropertyValue('--font-inter'),
    });
    probe.remove();
    return theme;
};

export const resolveChartColor = (theme: ChartTheme, role: ChartColorRole): string =>
    theme[role];

export const chartColorCssVariable = (role: ChartColorRole): string =>
    `var(${CHART_THEME_TOKENS[role]})`;

export const useChartTheme = (): ChartTheme | null => {
    const [theme, setTheme] = useState<ChartTheme | null>(null);

    useEffect(() => {
        const updateTheme = () => {
            const nextTheme = readChartTheme();
            setTheme((currentTheme) => {
                if (!nextTheme || !currentTheme) return nextTheme;
                return JSON.stringify(nextTheme) === JSON.stringify(currentTheme)
                    ? currentTheme
                    : nextTheme;
            });
        };

        updateTheme();
        const observer = new MutationObserver(updateTheme);
        observer.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['class'],
        });

        return () => observer.disconnect();
    }, []);

    return theme;
};
