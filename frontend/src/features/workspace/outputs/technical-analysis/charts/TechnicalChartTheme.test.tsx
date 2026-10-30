import React from 'react';
import { render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChartTheme } from '@/lib/chart-theme';
import type { CrosshairSyncState } from './useCrosshairSync';
import { TechnicalCandlestickChart } from './TechnicalCandlestickChart';
import { TechnicalIndicatorChart } from './TechnicalIndicatorChart';

interface MockSeries {
    kind: string;
    options: Record<string, unknown>;
    data: unknown[];
    applyOptions: ReturnType<typeof vi.fn>;
    setData: ReturnType<typeof vi.fn>;
    priceScale: ReturnType<typeof vi.fn>;
    createPriceLine: ReturnType<typeof vi.fn>;
    removePriceLine: ReturnType<typeof vi.fn>;
}

interface MockTimeScale {
    applyOptions: ReturnType<typeof vi.fn>;
    subscribeVisibleTimeRangeChange: ReturnType<typeof vi.fn>;
    unsubscribeVisibleTimeRangeChange: ReturnType<typeof vi.fn>;
    setVisibleRange: ReturnType<typeof vi.fn>;
    fitContent: ReturnType<typeof vi.fn>;
}

interface MockChart {
    options: Record<string, unknown>;
    series: MockSeries[];
    applyOptions: ReturnType<typeof vi.fn>;
    addSeries: ReturnType<typeof vi.fn>;
    removeSeries: ReturnType<typeof vi.fn>;
    remove: ReturnType<typeof vi.fn>;
    subscribeCrosshairMove: ReturnType<typeof vi.fn>;
    unsubscribeCrosshairMove: ReturnType<typeof vi.fn>;
    clearCrosshairPosition: ReturnType<typeof vi.fn>;
    setCrosshairPosition: ReturnType<typeof vi.fn>;
    timeScale: ReturnType<typeof vi.fn>;
    timeScaleApi: MockTimeScale;
}

const chartHarness = vi.hoisted(() => {
    const charts: MockChart[] = [];
    let theme: ChartTheme | null = null;

    const createSeries = (kind: string, options: Record<string, unknown>): MockSeries => {
        const series: MockSeries = {
            kind,
            options,
            data: [],
            applyOptions: vi.fn((nextOptions: Record<string, unknown>) => Object.assign(series.options, nextOptions)),
            setData: vi.fn((data: unknown[]) => { series.data = data; }),
            priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
            createPriceLine: vi.fn((priceLine) => ({ priceLine })),
            removePriceLine: vi.fn(),
        };
        return series;
    };

    const createChart = vi.fn((_container: HTMLElement, options: Record<string, unknown>) => {
        const timeScaleApi: MockTimeScale = {
            applyOptions: vi.fn(),
            subscribeVisibleTimeRangeChange: vi.fn(),
            unsubscribeVisibleTimeRangeChange: vi.fn(),
            setVisibleRange: vi.fn(),
            fitContent: vi.fn(),
        };
        const chart: MockChart = {
            options,
            series: [],
            applyOptions: vi.fn((nextOptions) => Object.assign(chart.options, nextOptions)),
            addSeries: vi.fn((definition: string, seriesOptions: Record<string, unknown>) => {
                const series = createSeries(definition, seriesOptions);
                chart.series.push(series);
                return series;
            }),
            removeSeries: vi.fn(),
            remove: vi.fn(),
            subscribeCrosshairMove: vi.fn(),
            unsubscribeCrosshairMove: vi.fn(),
            clearCrosshairPosition: vi.fn(),
            setCrosshairPosition: vi.fn(),
            timeScale: vi.fn(() => timeScaleApi),
            timeScaleApi,
        };
        charts.push(chart);
        return chart;
    });

    return {
        charts,
        createChart,
        getTheme: () => theme,
        setTheme: (nextTheme: ChartTheme | null) => { theme = nextTheme; },
    };
});

vi.mock('lightweight-charts', () => ({
    CandlestickSeries: 'candlestick',
    ColorType: { Solid: 0 },
    createChart: chartHarness.createChart,
    CrosshairMode: { Normal: 0 },
    HistogramSeries: 'histogram',
    LineSeries: 'line',
    LineStyle: { Solid: 0, Dashed: 1 },
}));

vi.mock('@/lib/chart-theme', async (importOriginal) => {
    const actual = await importOriginal<typeof import('@/lib/chart-theme')>();
    return { ...actual, useChartTheme: () => chartHarness.getTheme() };
});

const createTheme = (name: string): ChartTheme => new Proxy(
    { fontFamily: 'Inter' } as ChartTheme,
    { get: (target, property) => property === 'fontFamily' ? target.fontFamily : `${name}-${String(property)}` }
);

const candles = [
    { time: 1 as never, open: 10, high: 12, low: 9, close: 11 },
    { time: 2 as never, open: 11, high: 13, low: 10, close: 12 },
];
const volumes = [
    { time: 1 as never, value: 100, color: 'seriesUpMuted' as const },
    { time: 2 as never, value: 120, color: 'seriesDownMuted' as const },
];
const overlays = [{
    id: 'moving-average',
    data: [{ time: 1 as never, value: 10 }, { time: 2 as never, value: 11 }],
    color: 'seriesPrimary' as const,
}];
const lines = [{
    id: 'indicator',
    data: [{ time: 1 as never, value: 0.5 }, { time: 2 as never, value: 0.7 }],
    color: 'seriesSecondary' as const,
}];
const histograms = [{
    id: 'histogram',
    data: [
        { time: 1 as never, value: 1, color: 'seriesUpMuted' as const },
        { time: 2 as never, value: -1, color: 'seriesDownMuted' as const },
    ],
}];
const priceLines = [{ price: 0, color: 'seriesNeutral' as const, title: 'Zero' }];
const syncState = {
    activeCrosshairSourceId: null,
    activeRangeSourceId: null,
    crosshairTime: 1 as never,
    crosshairPoint: null,
    visibleTimeRange: { from: 1 as never, to: 2 as never },
    scrollPosition: null,
    requestCrosshair: vi.fn(),
    requestVisibleTimeRange: vi.fn(),
    requestScrollPosition: vi.fn(),
    activateCrosshairSource: vi.fn(),
    activateRangeSource: vi.fn(),
    clearCrosshairSource: vi.fn(),
    clearRangeSource: vi.fn(),
} satisfies CrosshairSyncState;

const Charts = () => (
    <>
        <TechnicalCandlestickChart
            candles={candles}
            volumes={volumes}
            overlays={overlays}
            syncId="price"
            syncState={syncState}
        />
        <TechnicalIndicatorChart
            lines={lines}
            histograms={histograms}
            priceLines={priceLines}
            syncId="indicator"
            syncState={syncState}
        />
    </>
);

describe('technical chart theme updates', () => {
    beforeEach(() => {
        chartHarness.charts.length = 0;
        chartHarness.createChart.mockClear();
        chartHarness.setTheme(createTheme('light'));
        vi.stubGlobal('ResizeObserver', class {
            observe() {}
            disconnect() {}
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    it('updates populated charts while retaining chart instances, data, and synchronization state', () => {
        const { rerender } = render(<Charts />);
        const [priceChart, indicatorChart] = chartHarness.charts;
        const allSeries = chartHarness.charts.flatMap((chart) => chart.series);
        const dataCallCounts = allSeries.map((series) => series.setData.mock.calls.length);
        const priceCrosshairCalls = priceChart.setCrosshairPosition.mock.calls.length;
        const indicatorCrosshairCalls = indicatorChart.setCrosshairPosition.mock.calls.length;
        const priceRangeCalls = priceChart.timeScaleApi.setVisibleRange.mock.calls.length;
        const indicatorRangeCalls = indicatorChart.timeScaleApi.setVisibleRange.mock.calls.length;

        chartHarness.setTheme(createTheme('dark'));
        rerender(<Charts />);

        expect(chartHarness.createChart).toHaveBeenCalledTimes(2);
        expect(chartHarness.charts).toHaveLength(2);
        expect(priceChart.applyOptions).toHaveBeenLastCalledWith(expect.objectContaining({
            layout: expect.objectContaining({ textColor: 'dark-axisText', fontFamily: 'Inter' }),
        }));
        expect(indicatorChart.applyOptions).toHaveBeenLastCalledWith(expect.objectContaining({
            layout: expect.objectContaining({ textColor: 'dark-axisText', fontFamily: 'Inter' }),
        }));
        expect(allSeries.map((series) => series.setData.mock.calls.length)).toEqual(dataCallCounts);
        expect(priceChart.setCrosshairPosition).toHaveBeenCalledTimes(priceCrosshairCalls);
        expect(indicatorChart.setCrosshairPosition).toHaveBeenCalledTimes(indicatorCrosshairCalls);
        expect(priceChart.timeScaleApi.setVisibleRange).toHaveBeenCalledTimes(priceRangeCalls);
        expect(indicatorChart.timeScaleApi.setVisibleRange).toHaveBeenCalledTimes(indicatorRangeCalls);
        expect(priceChart.series.find((series) => series.kind === 'candlestick')?.options.upColor)
            .toBe('dark-seriesUp');
        expect(indicatorChart.series.find((series) => series.kind === 'line')?.options.color)
            .toBe('dark-seriesSecondary');
        expect(allSeries.some((series) => series.data.some((point) =>
            typeof point === 'object' && point !== null && 'value' in point && point.value === 1
        )))
            .toBe(true);
    });
});
