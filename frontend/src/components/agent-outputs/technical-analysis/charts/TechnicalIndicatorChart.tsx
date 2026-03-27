import React, { useEffect, useMemo, useRef } from 'react';
import {
    BusinessDay,
    ColorType,
    createChart,
    CrosshairMode,
    HistogramSeries,
    IChartApi,
    ISeriesApi,
    IRange,
    LineSeries,
    LineStyle,
    MouseEventParams,
    Time,
    UTCTimestamp,
} from 'lightweight-charts';
import { CrosshairSyncState } from './useCrosshairSync';
import { TECHNICAL_PALETTE } from '../technicalPalette';

export type IndicatorLinePoint = { time: UTCTimestamp; value: number } | { time: UTCTimestamp };
export type IndicatorHistogramPoint =
    | { time: UTCTimestamp; value: number; color?: string }
    | { time: UTCTimestamp };

export interface IndicatorLineSeries {
    id: string;
    data: IndicatorLinePoint[];
    color: string;
    lineWidth?: 1 | 2 | 3 | 4;
}

export interface IndicatorHistogramSeries {
    id: string;
    data: IndicatorHistogramPoint[];
    color?: string;
    priceFormat?: {
        type: 'volume' | 'price' | 'custom';
        precision?: number;
        minMove?: number;
        formatter?: (price: number) => string;
    };
}

export interface IndicatorPriceLine {
    price: number;
    color: string;
    title?: string;
    style?: 'solid' | 'dashed';
    axisLabelColor?: string;
    axisLabelTextColor?: string;
}

type VisibleTimeRange = IRange<Time>;

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null;

const isBusinessDay = (time: Time): time is BusinessDay => {
    if (!isRecord(time)) return false;
    return (
        typeof time.year === 'number' &&
        typeof time.month === 'number' &&
        typeof time.day === 'number'
    );
};

const isUtcTimestamp = (value: number): value is UTCTimestamp => Number.isFinite(value);

interface TechnicalIndicatorChartProps {
    lines: IndicatorLineSeries[];
    histograms?: IndicatorHistogramSeries[];
    priceLines?: IndicatorPriceLine[];
    height?: number;
    showTime?: boolean;
    showTimeScale?: boolean;
    histogramScaleMargins?: { top?: number; bottom?: number };
    syncId: string;
    syncState: CrosshairSyncState;
}

const DEFAULT_HEIGHT = 200;
const normalizeTime = (time: Time): UTCTimestamp | null => {
    if (typeof time === 'number') return isUtcTimestamp(time) ? time : null;
    if (typeof time === 'string') {
        const parsed = Date.parse(time);
        if (Number.isNaN(parsed)) return null;
        const seconds = Math.floor(parsed / 1000);
        return isUtcTimestamp(seconds) ? seconds : null;
    }
    if (isBusinessDay(time)) {
        const utc = Date.UTC(time.year, time.month - 1, time.day);
        const seconds = Math.floor(utc / 1000);
        return isUtcTimestamp(seconds) ? seconds : null;
    }
    return null;
};

const resolveLineStyle = (style?: IndicatorPriceLine['style']) => {
    if (style === 'dashed') return LineStyle.Dashed;
    return LineStyle.Solid;
};

const findNearestTime = (times: UTCTimestamp[], target: UTCTimestamp): UTCTimestamp | null => {
    if (times.length === 0) return null;
    const first = times[0];
    const last = times[times.length - 1];
    if (target <= first) return first;
    if (target >= last) return last;
    let low = 0;
    let high = times.length - 1;
    while (low <= high) {
        const mid = Math.floor((low + high) / 2);
        const value = times[mid];
        if (value === target) return value;
        if (value < target) {
            low = mid + 1;
        } else {
            high = mid - 1;
        }
    }
    const left = times[Math.max(0, high)];
    const right = times[Math.min(times.length - 1, low)];
    return target - left <= right - target ? left : right;
};

export const TechnicalIndicatorChart: React.FC<TechnicalIndicatorChartProps> = ({
    lines,
    histograms = [],
    priceLines = [],
    height = DEFAULT_HEIGHT,
    showTime = false,
    showTimeScale = true,
    histogramScaleMargins,
    syncId,
    syncState,
}) => {
    const containerRef = useRef<HTMLDivElement | null>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const lineSeriesRef = useRef<ISeriesApi<'Line'>[]>([]);
    const histogramSeriesRef = useRef<ISeriesApi<'Histogram'>[]>([]);
    const priceLinesRef = useRef<ReturnType<ISeriesApi<'Line'>['createPriceLine']>[]>([]);
    const isSyncingRef = useRef(false);
    const lastEmittedRef = useRef<{ time: UTCTimestamp | null; pointKey: string } | null>(null);
    const pendingTimeRef = useRef<UTCTimestamp | null>(null);
    const pendingPointRef = useRef<{ x: number; y: number } | null>(null);
    const rafRef = useRef<number | null>(null);
    const rangeSyncGateRef = useRef(0);
    const activeCrosshairSourceIdRef = useRef<string | null>(syncState.activeCrosshairSourceId);
    const hasDataRef = useRef(false);
    const {
        requestCrosshair,
        requestVisibleTimeRange,
        activateCrosshairSource,
        clearCrosshairSource,
    } = syncState;

    const hasData = useMemo(() => {
        const lineHasValue = lines.some((line) =>
            line.data.some((point) => 'value' in point && typeof point.value === 'number')
        );
        const histHasValue = histograms.some((hist) =>
            hist.data.some((point) => 'value' in point && typeof point.value === 'number')
        );
        return lineHasValue || histHasValue;
    }, [lines, histograms]);
    const primarySeriesMap = useMemo(() => {
        const map = new Map<UTCTimestamp, number>();
        const source = lines[0]?.data ?? histograms[0]?.data ?? [];
        source.forEach((point) => {
            if ('value' in point && typeof point.value === 'number') {
                map.set(point.time, point.value);
            }
        });
        return map;
    }, [lines, histograms]);
    const primarySeriesTimes = useMemo(() => {
        const source = lines[0]?.data ?? histograms[0]?.data ?? [];
        return source
            .filter((point) => 'value' in point && typeof point.value === 'number')
            .map((point) => point.time)
            .sort((a, b) => a - b);
    }, [lines, histograms]);

    useEffect(() => {
        activeCrosshairSourceIdRef.current = syncState.activeCrosshairSourceId;
    }, [syncState.activeCrosshairSourceId]);

    useEffect(() => {
        const container = containerRef.current;
        if (!container) return undefined;

        const chart = createChart(container, {
            width: container.clientWidth,
            height,
            layout: {
                background: { type: ColorType.Solid, color: 'transparent' },
                textColor: '#94a3b8',
                fontSize: 11,
                fontFamily: 'ui-sans-serif, system-ui, -apple-system, sans-serif',
                attributionLogo: false,
            },
            grid: {
                vertLines: { color: 'rgba(30, 41, 59, 0.6)' },
                horzLines: { color: 'rgba(30, 41, 59, 0.6)' },
            },
            crosshair: { mode: CrosshairMode.Normal },
            rightPriceScale: { borderColor: 'rgba(51, 65, 85, 0.7)' },
            timeScale: {
                borderColor: 'rgba(51, 65, 85, 0.7)',
                rightOffset: 0,
                barSpacing: 6,
                fixLeftEdge: true,
                fixRightEdge: true,
                lockVisibleTimeRangeOnResize: true,
            },
            handleScroll: {
                mouseWheel: true,
                pressedMouseMove: true,
                horzTouchDrag: true,
            },
            handleScale: {
                mouseWheel: true,
                pinch: true,
                axisPressedMouseMove: true,
            },
        });

        const lineSeries = Array.from({ length: lines.length }, () =>
            chart.addSeries(LineSeries, {
                color: '#60a5fa',
                lineWidth: 2,
            })
        );
        const histogramSeries = Array.from({ length: histograms.length }, () =>
            chart.addSeries(HistogramSeries, {
                color: 'rgba(148, 163, 184, 0.35)',
                priceScaleId: '',
            })
        );

        chartRef.current = chart;
        lineSeriesRef.current = lineSeries;
        histogramSeriesRef.current = histogramSeries;

        const handleResize = () => {
            chart.applyOptions({ width: container.clientWidth });
        };

        const resizeObserver = new ResizeObserver(handleResize);
        resizeObserver.observe(container);

        const handleCrosshairMove = (param: MouseEventParams) => {
            if (isSyncingRef.current) {
                isSyncingRef.current = false;
                return;
            }
            const anchorSeries =
                lineSeriesRef.current[0] ?? histogramSeriesRef.current[0] ?? null;
            if (!param || !param.time || !param.seriesData || !anchorSeries || !param.point) {
                return;
            }
            if (!param.seriesData.get(anchorSeries)) {
                return;
            }
            const normalized = normalizeTime(param.time);
            if (normalized === null) {
                return;
            }
            const bounds = containerRef.current?.getBoundingClientRect();
            if (!bounds) return;
            const point = {
                x: bounds.left + param.point.x,
                y: bounds.top + param.point.y,
            };
            if (activeCrosshairSourceIdRef.current && activeCrosshairSourceIdRef.current !== syncId) {
                return;
            }
            pendingTimeRef.current = normalized;
            pendingPointRef.current = point;
            if (rafRef.current !== null) {
                return;
            }
            rafRef.current = window.requestAnimationFrame(() => {
                rafRef.current = null;
                const next = pendingTimeRef.current;
                if (next === null) return;
                const nextPoint = pendingPointRef.current;
                const pointKey = nextPoint
                    ? `${Math.round(nextPoint.x)}:${Math.round(nextPoint.y)}`
                    : 'null';
                if (lastEmittedRef.current?.time === next && lastEmittedRef.current?.pointKey === pointKey) {
                    return;
                }
                lastEmittedRef.current = { time: next, pointKey };
                requestCrosshair(syncId, next, nextPoint);
            });
        };

        chart.subscribeCrosshairMove(handleCrosshairMove);
        const handleMouseEnter = () => {
            activateCrosshairSource(syncId);
        };
        const handleMouseLeave = () => {
            clearCrosshairSource(syncId);
            if (rafRef.current !== null) {
                window.cancelAnimationFrame(rafRef.current);
                rafRef.current = null;
            }
            pendingTimeRef.current = null;
            pendingPointRef.current = null;
            lastEmittedRef.current = null;
        };
        container.addEventListener('mouseenter', handleMouseEnter);
        container.addEventListener('mouseleave', handleMouseLeave);

        const handleVisibleRangeChange = (range: VisibleTimeRange | null) => {
            if (rangeSyncGateRef.current > 0) {
                rangeSyncGateRef.current -= 1;
                return;
            }
            if (!range) return;
            requestVisibleTimeRange(syncId, range);
        };
        chart.timeScale().subscribeVisibleTimeRangeChange(handleVisibleRangeChange);

        return () => {
            resizeObserver.disconnect();
            chart.unsubscribeCrosshairMove(handleCrosshairMove);
            chart.timeScale().unsubscribeVisibleTimeRangeChange(handleVisibleRangeChange);
            container.removeEventListener('mouseenter', handleMouseEnter);
            container.removeEventListener('mouseleave', handleMouseLeave);
            if (rafRef.current !== null) {
                window.cancelAnimationFrame(rafRef.current);
            }
            chart.remove();
            chartRef.current = null;
            lineSeriesRef.current = [];
            histogramSeriesRef.current = [];
            priceLinesRef.current = [];
        };
    }, [
        activateCrosshairSource,
        clearCrosshairSource,
        height,
        histograms.length,
        lines.length,
        requestCrosshair,
        requestVisibleTimeRange,
        syncId,
    ]);

    useEffect(() => {
        if (!chartRef.current) return;
        lineSeriesRef.current.forEach((series, index) => {
            const line = lines[index];
            if (!line) return;
            series.applyOptions({
                color: line.color,
                lineWidth: line.lineWidth ?? 2,
            });
            series.setData(line.data ?? []);
        });
        histogramSeriesRef.current.forEach((series, index) => {
            const histogram = histograms[index];
            if (!histogram) return;
            series.applyOptions({
                color: histogram.color ?? TECHNICAL_PALETTE.histogram,
                priceFormat: histogram.priceFormat,
            });
            series.setData(histogram.data ?? []);
        });
        if (hasData && !hasDataRef.current) {
            chartRef.current.timeScale().fitContent();
            hasDataRef.current = true;
        } else if (!hasData) {
            hasDataRef.current = false;
        }
    }, [lines, histograms, hasData]);

    useEffect(() => {
        if (!chartRef.current) return;
        chartRef.current.applyOptions({
            timeScale: {
                visible: showTimeScale,
                timeVisible: showTime,
                secondsVisible: showTime,
            },
        });
    }, [showTime, showTimeScale]);

    useEffect(() => {
        if (!chartRef.current) return;
        const margins = {
            top: histogramScaleMargins?.top ?? 0.7,
            bottom: histogramScaleMargins?.bottom ?? 0,
        };
        histogramSeriesRef.current.forEach((series) => {
            series.priceScale().applyOptions({ scaleMargins: margins });
        });
    }, [histogramScaleMargins]);

    useEffect(() => {
        if (!chartRef.current) return;
        const anchorSeries =
            lineSeriesRef.current[0] ?? histogramSeriesRef.current[0] ?? null;
        if (!anchorSeries) return;
        if (syncState.activeCrosshairSourceId === syncId) return;
        if (!syncState.crosshairTime) {
            isSyncingRef.current = true;
            chartRef.current.clearCrosshairPosition();
            return;
        }
        const snapped = findNearestTime(primarySeriesTimes, syncState.crosshairTime);
        if (snapped === null) return;
        const price = primarySeriesMap.get(snapped);
        if (price === undefined) {
            return;
        }
        isSyncingRef.current = true;
        chartRef.current.setCrosshairPosition(price, snapped, anchorSeries);
    }, [primarySeriesMap, primarySeriesTimes, syncId, syncState.activeCrosshairSourceId, syncState.crosshairTime]);

    useEffect(() => {
        if (!chartRef.current) return;
        if (syncState.activeRangeSourceId === syncId) return;
        if (!syncState.visibleTimeRange) return;
        rangeSyncGateRef.current = 1;
        chartRef.current.timeScale().setVisibleRange(syncState.visibleTimeRange);
    }, [syncId, syncState.activeRangeSourceId, syncState.visibleTimeRange]);

    useEffect(() => {
        const series = lineSeriesRef.current[0];
        if (!series) return;
        priceLinesRef.current.forEach((line) => series.removePriceLine(line));
        priceLinesRef.current = priceLines.map((line) =>
            series.createPriceLine({
                price: line.price,
                color: line.color,
                lineStyle: resolveLineStyle(line.style),
                axisLabelVisible: true,
                title: line.title ?? '',
                axisLabelColor: line.axisLabelColor,
                axisLabelTextColor: line.axisLabelTextColor,
            })
        );
    }, [priceLines]);

    return (
        <div className="w-full">
            <div ref={containerRef} className="w-full" style={{ height }} />
            {!hasData && (
                <div className="mt-3 text-xs text-outline">
                    Indicator data unavailable for this timeframe.
                </div>
            )}
        </div>
    );
};
